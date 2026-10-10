from pyngrok import ngrok

# Start tunnel
public_url = ngrok.connect(5000)
print(f"🌐 Public URL: {public_url}")
print("Share this URL with your phone!")
input("Press Enter to stop...")