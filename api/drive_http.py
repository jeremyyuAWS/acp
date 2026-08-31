"""Isolate ordinary Drive request execution from a shared SDK service transport.

Google's httplib2 transport is not thread-safe. Discovery shares one service
across its folder pool; each execute() must own its socket pool instead.
This is transport isolation, not native-process crash containment.
"""
import copy

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.http import HttpRequest


def isolated_request_builder(credentials, timeout):
    """SDK requestBuilder retaining auth, retries and parsing, without shared sockets.

    A new transport per execution trades connection reuse for explicit ownership
    and deterministic cleanup. Credentials are shallow-copied so token/expiry
    updates during a refresh are local to this execution. Scope is execute(),
    not SDK batch requests or MediaIoBaseDownload's direct transport access.
    """
    class IsolatedRequest(HttpRequest):
        def execute(self, http=None, num_retries=0):
            if http is not None:
                # Explicit transport overrides remain owned by their caller.
                return super().execute(http=http, num_retries=num_retries)
            transport = httplib2.Http(timeout=timeout)
            try:
                authorized = AuthorizedHttp(copy.copy(credentials), http=transport)
                return super().execute(http=authorized, num_retries=num_retries)
            finally:
                transport.close()

    return IsolatedRequest
