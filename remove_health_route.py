import os
os.chdir(r'D:\xampp\htdocs\lat1')

# Read main.py
f = open('app/main.py', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

# Remove the @app.get("/health") route and def health_root function
# Find the pattern and remove it
pattern = '''@app.get("/health", include_in_schema=False)
def health_root():'''

if pattern in content:
    content = content.replace(pattern, '')
    print("Removed @app.get('/health') and def health_root pattern")
else:
    print("Pattern not found, checking alternative...")
    # Try just removing the route
    if '@app.get("/health")' in content:
        # Find and remove
        idx = content.find('@app.get("/health")')
        # Find the function
        func_idx = content.find('def health_root', idx)
        if func_idx >= 0:
            # Find where the function ends - look for next @app.decorator or @app.on_event
            next_decorator = content.find('@app.', func_idx + 20)
            if next_decorator >= 0:
                content = content[:idx] + content[next_decorator:]
                print("Removed route and function to next decorator")
            else:
                content = content[:idx] + content[func_idx+200:]  # Remove generous amount
                print("Removed route and function generously")
        else:
            print("def health_root not found after route")
    else:
        print("@app.get('/health') not found")

# Write back
f = open('app/main.py', 'w', encoding='utf-8', errors='ignore')
f.write(content)
f.close()
print("main.py updated")