"""Version successful release checks by the deployed evaluator, never by filename."""
from hashlib import sha256
import json
import os
from pathlib import Path


def evaluator_identity():
    """No reuse on an unversioned development runtime or an unreadable engine.

    Build identity includes packaged libraries. Source/configuration hashes also invalidate
    a check when a mounted analyser or rubric changes without a new image. Environment
    values are hashed, never recorded (they may contain provider credentials).
    """
    version = os.environ.get('ACP_BUILD_VERSION') or os.environ.get('ACP_VERSION')
    if not version or version == 'dev':
        return None
    # A stable endpoint/model name does not version a mutable external evaluator.
    # Do not reuse until those adapters expose an immutable evaluator revision.
    if (os.environ.get('ACP_VERAPDF_REST', '').strip()
            or os.environ.get('ACP_SCANNED_PDF_TIER_A', '').strip().lower()
            in {'1', 'true', 'yes', 'on'}):
        return None
    root = Path(__file__).resolve().parents[1]
    engine = Path(os.environ.get('ACP_PDF_ENGINE') or root / 'engine/pdf-analyser')
    if not (engine / 'analysers').is_dir():
        return None
    digest = sha256(version.encode())
    try:
        for directory, pattern in ((root / 'api', '*.py'), (root / 'config', '*.json'),
                                   (engine, '*.py')):
            for path in sorted(directory.rglob(pattern)):
                if '__pycache__' in path.parts:
                    continue
                digest.update(str(path.relative_to(directory)).encode())
                digest.update(path.read_bytes())
        # These can change evaluator behaviour without changing source or the image.
        values = {key: value for key, value in os.environ.items()
                  if key.startswith(('ACP_', 'OLLAMA_'))}
        digest.update(json.dumps(values, sort_keys=True).encode())
    except (OSError, ValueError):
        return None
    return 'release-evaluator.v1:' + digest.hexdigest()


def scope_identity(scope):
    # None (legacy unrestricted) and an explicitly empty selection are different.
    return None if scope is None else {code: sorted(formats) for code, formats in scope.items()}
