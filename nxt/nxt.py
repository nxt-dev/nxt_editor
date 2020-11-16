import warnings

from session import Session
Nxt = Session

msg = ("'Nxt' object is deprecated, use 'Session' object, imported from "
       "nxt.session")
warnings.warn(msg)
