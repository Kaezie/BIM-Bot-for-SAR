"""Preview the UI without hardware; Playwright injects API and auth fixtures.

Run from the workspace root with: python scripts/preview_ui.py
"""
from pathlib import Path
import sys
from flask import Flask, render_template, request
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from features.monitoring_profile import PROFILE
app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.context_processor
def monitoring_profile_context():
    return {'monitoring_profile': dict(PROFILE)}


@app.route('/')
def dashboard():
    return render_template('dashboard.html', supabase_url='https://example.supabase.co', supabase_anon_key='preview')


@app.route('/login')
@app.route('/signup')
def login():
    return render_template('login.html', signup=request.path == '/signup', supabase_url='https://example.supabase.co', supabase_anon_key='preview')


@app.get('/testing')
def testing():
    return render_template('testing.html', supabase_url='https://example.supabase.co', supabase_anon_key='preview')


if __name__ == '__main__':
    app.run(port=5051)
