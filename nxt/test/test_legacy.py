# Builtin
import unittest
import json
import os
import re

# Internal
from nxt import nxt_path
from nxt.constants import GRAPH_VERSION
from nxt.session import Session

os.chdir(os.path.dirname(os.path.abspath(__file__)))


class LegacyFileConversion(unittest.TestCase):

    def test_auto_update(self):
        self.stage = Session().load_file("legacy/0.45.0_TopLayer.nxt")
        self.file_data = self.stage.get_layer_save_data(0)
        self.file_data = json.dumps(self.file_data, indent=4, sort_keys=False)
        file_path = "legacy/0.45.0_to_LATEST.nxt"
        real_path = nxt_path.full_file_expand(file_path)
        self.proof_data = dynamic_version(real_path)
        self.assertEqual(self.proof_data, self.file_data)


def dynamic_version(real_path, version=GRAPH_VERSION.VERSION_STR):
    version = '"' + version + '"'
    with open(real_path, 'r') as file_object:
        json_data = file_object.read()
        pattern = r"((\"version\": )([0-9\.\"]*)(\,))"
        ref, num = re.search(pattern, json_data).group(0, 3)
        cur_version = ref.replace(num, version)
        proof_data = json_data.replace(ref, cur_version)
        return proof_data
