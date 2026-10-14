"""Manual connection check: uploads test/hello.txt to the configured live bucket.

Run from the workspace root with: python scripts/check_supabase_storage.py
This is a utility script, not part of the offline test suite.
"""

import os
from pathlib import Path


def main():
    from dotenv import load_dotenv
    from supabase import create_client

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    client = create_client(
        os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY']
    )
    bucket = os.environ.get('SUPABASE_STORAGE_BUCKET', 'recordings')
    storage = client.storage.from_(bucket)
    storage.upload('test/hello.txt', b'hello', {'upsert': 'true'})
    print('Upload OK:', storage.list('test'))


if __name__ == '__main__':
    main()
