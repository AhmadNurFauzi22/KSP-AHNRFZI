import os
os.chdir(r'D:\xampp\htdocs\lat1')

f = open('app/templates/rbac_it_pusat.html', 'r', encoding='utf-8', errors='ignore')
content = f.read()
f.close()

# Remove the orphaned {% endblock %} at line 184
# The line is: '{% endblock %}'
# We need to remove it, but keep the newline after it (line 185 is empty)

lines = content.split('\n')

# Find and remove the orphaned endblock at line 184 (index 183)
# Line 184 is index 183, and line 185 (index 184) is empty
# We'll remove index 183 (the {% endblock %} tag)

if '{% endblock %}' in lines[183]:
    # Remove the orphaned endblock line
    del lines[183]
    # The empty line after it (index 184) can stay or be removed
    # Let's keep the structure clean by removing it too if it's just empty
    if len(lines) > 184 and lines[184].strip() == '':
        del lines[184]

new_content = '\n'.join(lines)
f = open('app/templates/rbac_it_pusat.html', 'w', encoding='utf-8', errors='ignore')
f.write(new_content)
f.close()

print('File updated. Removed orphaned {% endblock %} at line 184')