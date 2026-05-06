import re
with open('renew_website/templates/deye/dashboard.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Remove the first declaration and its content
pattern1 = re.compile(r'\s*async function getChargingRecommendation\(\) \{\s*const content = document\.getElementById\(\'charging-content\'\);\s*const actionsFooter = document\.getElementById\(\'recommendation-actions\'\);.*?\}\n', re.DOTALL)
text = pattern1.sub('\n\n', text, count=1)

# Add actionsFooter to the bottom one
pattern2 = re.compile(r'(async function getChargingRecommendation\(\) \{\s*const content = document\.getElementById\(\'charging-content\'\);\n)')
repl2 = r'\1    const actionsFooter = document.getElementById(\'recommendation-actions\');\n    actionsFooter.classList.add(\'d-none\');\n'
text = pattern2.sub(repl2, text)

# Set the variable and remove d-none
pattern3 = re.compile(r'(let p_mode = sc1\.mode; // Algorithm selected mode\n)')
repl3 = r'\1        lastRecommendationMode = p_mode;\n'
text = pattern3.sub(repl3, text)

pattern4 = re.compile(r'(\s*<div class=\"alert alert-secondary mt-2 mb-0\">.*?<\/div>\n\s*`;\n)', re.DOTALL)
repl4 = r'\1        actionsFooter.classList.remove(\'d-none\');\n'
text = pattern4.sub(repl4, text)

with open('renew_website/templates/deye/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(text)
print("done")
