"""마카롱 API 도구 — 텍스트 편집이 그 값만 바꾸는지, cas 충돌 때 다시 읽는지, dev 서버만 부르는지"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'device_flows'))
import macaron_api  # noqa: E402
import macaron_edit  # noqa: E402

DOC = '''{
  "mid": "ABC",
  "big": 9007199254740993,
  "wallet": {"crystal": {"amt": 100}},
  "inventory": {
    "pets": [
      {"id": 1, "lv": 1},
      {"id": 2, "lv": 2},
      {"id": 3, "lv": 3}
    ],
    "one": [
      {"id": 9}
    ],
    "empty": []
  }
}'''


class TextEditTest(unittest.TestCase):
    def test_set_keeps_other_text(self):
        new, old = macaron_edit.text_set(DOC, ['wallet', 'crystal', 'amt'], '101')
        self.assertEqual(old, '100')
        self.assertEqual(new, DOC.replace('"amt": 100', '"amt": 101'))
        self.assertIn('9007199254740993', new)   # int64 를 다시 직렬화하지 않는다

    def test_remove_middle_last_and_only(self):
        for path, gone in ((['inventory', 'pets', '1'], 2), (['inventory', 'pets', '2'], 3), (['inventory', 'one', '0'], 9)):
            new, item = macaron_edit.text_remove(DOC, path)
            self.assertEqual(json.loads(item)['id'], gone)
            want = json.loads(DOC)
            macaron_edit.get_in(want, path[:-1]).pop(int(path[-1]))
            self.assertEqual(json.loads(new), want, path)

    def test_insert_restores_exact_text(self):
        for path in (['inventory', 'pets', '0'], ['inventory', 'pets', '1'], ['inventory', 'pets', '2'], ['inventory', 'one', '0']):
            removed, item = macaron_edit.text_remove(DOC, path)
            back = macaron_edit.text_insert(removed, path[:-1], int(path[-1]), item)
            self.assertEqual(json.loads(back), json.loads(DOC), path)
        self.assertEqual(json.loads(macaron_edit.text_insert(DOC, ['inventory', 'empty'], 0, '{"id": 5}'))['inventory']['empty'], [{'id': 5}])
        with self.assertRaises(IndexError):
            macaron_edit.text_insert(DOC, ['inventory', 'pets'], 5, '{}')


class FakeServer:
    def __init__(self, text, conflicts=0):
        self.text, self.cas, self.conflicts, self.saves = text, 1, conflicts, []

    def get(self, env, key, bucket='gb-member'):
        return self.text, str(self.cas)

    def save(self, env, key, text, cas, bucket='gb-member'):
        if self.conflicts:
            self.conflicts -= 1
            self.cas += 1     # 앱이 그 사이 문서를 바꿨다
            raise macaron_api.CasConflict('x')
        assert cas == str(self.cas)
        self.saves.append(text)
        self.text, self.cas = text, self.cas + 1
        return str(self.cas)


class WriteTest(unittest.TestCase):
    def run_edit(self, server, *argv):
        out = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(macaron_api, 'get', server.get), mock.patch.object(macaron_api, 'save', server.save), \
                mock.patch.object(macaron_edit, 'out', out.append), mock.patch.object(macaron_edit.time, 'sleep', lambda s: None):
            code = macaron_edit.main([*argv, '--env', 'gb-x', '--key', 'member:ABC', '--out-dir', d])
            saved = [f for f in os.listdir(d) if f.endswith('.removed.json')]
            extra = None
            if saved:
                with open(os.path.join(d, saved[0]), encoding='utf-8') as f:
                    extra = json.load(f)
        return code, out[-1], extra

    def test_set_with_expect(self):
        s = FakeServer(DOC)
        code, res, _ = self.run_edit(s, 'set', 'wallet.crystal.amt', '50', '--expect', '100')
        self.assertEqual((code, res['ok'], res['old'], res['new']), (0, True, 100, 50))
        self.assertEqual(s.text, DOC.replace('"amt": 100', '"amt": 50'))

    def test_expect_mismatch_does_not_save(self):
        s = FakeServer(DOC)
        code, res, _ = self.run_edit(s, 'set', 'wallet.crystal.amt', '50', '--expect', '7')
        self.assertEqual((code, res['current'], s.saves), (6, 100, []))

    def test_cas_conflict_rereads_and_retries(self):
        s = FakeServer(DOC, conflicts=2)
        code, res, _ = self.run_edit(s, 'set', 'wallet.crystal.amt', '50')
        self.assertEqual((code, res['attempts'], len(s.saves)), (0, 3, 1))
        s = FakeServer(DOC, conflicts=3)
        code, res, _ = self.run_edit(s, 'set', 'wallet.crystal.amt', '50')
        self.assertEqual((code, s.saves), (3, []))

    def test_remove_then_insert_by_id(self):
        s = FakeServer(DOC)
        code, res, saved = self.run_edit(s, 'remove', 'inventory.pets.@id=3')
        self.assertEqual((code, res['path'], res['removed']['id']), (0, 'inventory.pets.2', 3))
        self.assertEqual([p['id'] for p in json.loads(s.text)['inventory']['pets']], [1, 2])
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(saved, f)
        try:
            code, res, _ = self.run_edit(s, 'insert', 'inventory.pets.2', '--saved', f.name)
        finally:
            os.remove(f.name)
        self.assertEqual((code, json.loads(s.text)), (0, json.loads(DOC)))

    def test_remove_missing_and_referenced(self):
        s = FakeServer(DOC)
        code, res, _ = self.run_edit(s, 'remove', 'inventory.pets.@id=77')
        self.assertEqual((code, res.get('already'), s.saves), (0, True, []))
        doc = json.loads(DOC)
        doc['equipped'] = [2, 2]
        s = FakeServer(json.dumps(doc, indent=2))
        code, res, _ = self.run_edit(s, 'remove', 'inventory.pets.@id=2', '--max-refs', '2')
        self.assertEqual((code, s.saves), (6, []))


class GuardTest(unittest.TestCase):
    def test_only_dev_macaron(self):
        self.assertEqual(macaron_api.base_url('gb-qa-126'), 'https://macaron.gb-qa-126.stove.devspie.com')
        for bad in ('real', 'gb-qa-126.evil.com/x', 'gb_qa', '', None):
            with self.assertRaises(macaron_api.MacaronError):
                macaron_api.base_url(bad)

    def test_states_pass_env_and_key(self):
        import states
        calls = []
        with mock.patch.object(states, '_run', lambda cmd: calls.append(cmd) or (0, {'ok': True, 'exists': True, 'value': 1})):
            states.get_field('gb-x', 'MID', 'wallet.a', '/tmp')
            states.set_field('gb-x', 'MID', 'wallet.a', 2, '/tmp', expect=1)
        self.assertEqual(calls[0][2:4], ['peek', 'wallet.a'])
        self.assertEqual(calls[1][2:9], ['set', 'wallet.a', '2', '--expect', '1', '--env', 'gb-x'])
        self.assertTrue(all('member:MID' in c for c in calls))


if __name__ == '__main__':
    unittest.main()
