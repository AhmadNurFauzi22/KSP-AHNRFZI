import os
os.chdir(r'D:\xampp\htdocs\lat1')

# Read main.py
f = open('app/main.py', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

# Remove the problematic health_root function and its route
# The error is at line 96, let's find and remove the health_root function

# Find "def health_root" and remove it and the route above it
# Let's search for the pattern and remove it

# First, let me check the current state around line 96
idx = content.find('def health_root')
if idx >= 0:
    # Remove from def health_root to the next @app.on_event
    event_idx = content.find('@app.on_event', idx)
    if event_idx >= 0:
        # Remove the function and the route above it
        # Actually, let me just remove the route @app.get("/health") and the function
        # Find the @app.get("/health") position
        route_pos = content.find('@app.get("/health")')
        if route_pos >= 0:
            # Find the function start
            func_pos = content.rfind('def health_root', 0, route_pos)
            if func_pos >= 0:
                # Remove from func_pos to after the function
                # The function ends at the next decorator or end of relevant section
                # Let me just remove a large segment
                content = content[:func_pos] + content[event_idx if event_idx > 0 else func_pos+200:]
                print(f"Removed health_root function and route")
            else:
                # Just remove the route
                content = content[:route_pos] + content[route_pos+len('@app.get("/health")'):]
                print("Removed route only")
        else:
            print("@app.get('/health') not found after cleanup")
    else:
        print("event_idx not found")
else:
    print("def health_root not found - already cleaned up")

# Write back
f = open('app/main.py', 'w', encoding='utf-8', errors='ignore')
f.write(content)
f.close()
print("main.py cleaned up")