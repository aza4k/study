import os
import sys

def fix_broken_translations():
    # Search in the current directory (including venv)
    search_path = os.getcwd()
    print(f"Scanning {search_path} for broken translation files...")

    fixed_files = []

    for root, dirs, files in os.walk(search_path):
        for file in files:
            if file.endswith('.po'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Check for the invalid token
                    if 'plural=EXPRESSION' in content:
                        print(f"Found broken file: {file_path}")
                        
                        # Fix for Karakalpak (kaa) - Single form
                        if '/kaa/' in file_path:
                            new_content = content.replace('nplurals=INTEGER; plural=EXPRESSION;', 'nplurals=1; plural=0;')
                        # Fix for others - Standard 2 forms
                        else:
                            new_content = content.replace('nplurals=INTEGER; plural=EXPRESSION;', 'nplurals=2; plural=(n != 1);')
                        
                        # Write the fix
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        
                        fixed_files.append(file_path)
                        print(f"Fixed: {file_path}")

                except Exception as e:
                    print(f"Skipping {file_path}: {e}")

    if fixed_files:
        print(f"\nSuccessfully fixed {len(fixed_files)} files.")
        print("Recompiling messages (this may take a moment)...")
        os.system("python manage.py compilemessages")
        print("Done!")
    else:
        print("No files with 'plural=EXPRESSION' found.")

if __name__ == "__main__":
    fix_broken_translations()
