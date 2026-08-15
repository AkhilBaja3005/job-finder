# Custom Rule: Strict Control of Remote Git Pushes

1. **NEVER run `git push` or push code to remote repositories (`origin`, `main`, etc.) automatically.**
2. **ALWAYS wait for the user's explicit request ("push to origin", "push the changes") before running any push command.**
3. All code modifications, local testing, and local commits must remain strictly local until explicit permission is given.
