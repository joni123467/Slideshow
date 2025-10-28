import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from slideshow.media import _escape_cifs_option, _format_cifs_option


def test_escape_cifs_option_escapes_required_characters():
    raw = 'pa,ss\\wo"rd'
    escaped = _escape_cifs_option(raw)
    assert escaped == 'pa\\,ss\\\\wo\\"rd'


def test_format_cifs_option_preserves_quotes_in_password():
    password = '$92J"5K4vOL3N/G$'
    formatted = _format_cifs_option("password", password)
    assert formatted == 'password=$92J\\"5K4vOL3N/G$'
