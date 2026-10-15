"""Preview the UI without hardware; Playwright injects API and auth fixtures.

Run from the workspace root with: python scripts/preview_ui.py
"""
from pathlib import Path
from flask import Flask, render_template, request
root = Path(__file__).resolve().parents[1]
app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))


@app.route('/')
def dashboard():
    return render_template('dashboard.html', supabase_url='https://example.supabase.co', supabase_anon_key='preview')


@app.route('/login')
@app.route('/signup')
def login():
    return render_template('login.html', signup=request.path == '/signup', supabase_url='https://example.supabase.co', supabase_anon_key='preview')


if __name__ == '__main__':
    app.run(port=5051)
