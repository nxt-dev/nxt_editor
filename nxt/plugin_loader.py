# Built-in
import os
import imp
import logging

# Internal
from constants import PLUGIN_DIRS

_nxt_loaded_plugin_module_names = []
_nxt_loaded_plugin_modules = []

logger = logging.getLogger('nxt.plugins')


def load_plugins():
    global _nxt_loaded_plugin_module_names
    global _nxt_loaded_plugin_modules
    logger.info('Loading plugins.')
    for plugin_dir in PLUGIN_DIRS:
        if not os.path.isdir(plugin_dir):
            continue
        for file_name in os.listdir(plugin_dir):
            mod_name, _ = os.path.splitext(file_name)
            if mod_name in _nxt_loaded_plugin_module_names:
                continue
            try:
                found = imp.find_module(mod_name, [plugin_dir])
            except ImportError:
                continue
            mod = imp.load_module(mod_name, *found)
            _nxt_loaded_plugin_module_names += [mod_name]
            _nxt_loaded_plugin_modules += [mod]
