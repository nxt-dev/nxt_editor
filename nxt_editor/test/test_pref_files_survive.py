"""Saving a layer does not fail on a damaged editor cache.

The editor cache and prefs were written by emptying the file and then
writing to it. Another editor reading at that moment (Maya and standalone
share these files), or a write that failed part way, found an empty file,
and every later read raised, so saving a layer failed with
"EOFError: Ran out of input" when it noted the file as the last one opened.
"""
# Builtin
import os
import pickle
import shutil
import tempfile
import threading
import unittest

# Internal
from nxt_editor import user_dir


class PrefFilesSurvive(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_prefs_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache_path = os.path.join(self.tmp, 'editor_cache')
        self.json_path = os.path.join(self.tmp, 'prefs.json')

    def load(self, path):
        with open(path, 'rb') as fp:
            return pickle.load(fp)

    def test_an_empty_cache_can_be_written(self):
        cache = user_dir.PicklePref(self.cache_path)
        open(self.cache_path, 'wb').close()
        cache['last'] = 'graph.nxt'
        self.assertEqual({'last': 'graph.nxt'}, self.load(self.cache_path))

    def test_a_cut_off_cache_can_be_written(self):
        cache = user_dir.PicklePref(self.cache_path)
        cache['first'] = 1
        with open(self.cache_path, 'rb') as fp:
            data = fp.read()
        with open(self.cache_path, 'wb') as fp:
            fp.write(data[:len(data) // 2])
        cache['second'] = 2
        self.assertEqual(2, cache['second'])
        self.assertEqual({'first': 1, 'second': 2},
                         self.load(self.cache_path))

    def test_a_cache_opened_empty_can_be_read(self):
        open(self.cache_path, 'wb').close()
        cache = user_dir.PicklePref(self.cache_path)
        self.assertIsNone(cache.get('last'))
        cache['last'] = 'graph.nxt'
        self.assertEqual('graph.nxt', cache['last'])

    def test_broken_json_prefs_can_be_written(self):
        prefs = user_dir.JsonPref(self.json_path)
        prefs['a'] = 1
        with open(self.json_path, 'w') as fp:
            fp.write('{"a": ')
        prefs['b'] = 2
        self.assertEqual(1, prefs['a'])
        self.assertEqual(2, prefs['b'])

    def test_writing_leaves_no_temporary_files(self):
        cache = user_dir.PicklePref(self.cache_path)
        cache['a'] = 1
        prefs = user_dir.JsonPref(self.json_path)
        prefs['a'] = 1
        self.assertEqual(['editor_cache', 'prefs.json'],
                         sorted(os.listdir(self.tmp)))

    def test_another_editor_never_reads_half_a_cache(self):
        writer = user_dir.PicklePref(self.cache_path)
        writer['recent'] = []
        errors = []
        done = threading.Event()

        def read():
            while not done.is_set():
                try:
                    with open(self.cache_path, 'rb') as fp:
                        pickle.load(fp)
                except PermissionError:
                    pass  # Windows, mid replace. Not a broken file.
                except Exception as err:
                    errors.append(err)
                    return

        reader = threading.Thread(target=read)
        reader.start()
        try:
            for i in range(300):
                writer['recent'] = ['graph_{}.nxt'.format(n)
                                    for n in range(i % 50)]
        finally:
            done.set()
            reader.join()
        self.assertEqual([], errors)


if __name__ == '__main__':
    unittest.main()
