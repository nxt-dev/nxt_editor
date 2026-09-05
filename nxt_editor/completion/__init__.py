"""Host-aware code completion for the nxt code editor.

A small MVC stack, imported explicitly by consumers (this __init__ stays
free of Qt so the model/host layers are headless-testable):
    * Model      -- hosts.py (DCC namespace providers), sources.py, model.py
    * View       -- popup.py (CompletionPopup)
    * Controller -- controller.py (CompletionController)

The code editor widget owns a CompletionController and delegates to it.
"""
import logging

import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)
