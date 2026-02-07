# Fix Instructions for npm Permission Issues

## Issue Summary
1. npm cache has root-owned files causing permission errors
2. Tailwind CSS version mismatch (v4 installed, v3.4.0 in package.json)

## Solution Steps

### Step 1: Fix npm Cache Permissions
Run this command in your terminal:
```bash
sudo chown -R $(whoami) ~/.npm
```

### Step 2: Clean npm Cache
```bash
npm cache clean --force
```

### Step 3: Fix Tailwind CSS Version
Since we can't delete node_modules due to permissions, we'll force install the correct version:

```bash
cd /Users/aditya/Documents/EMT/EasyMyTicket/frontend
npm install tailwindcss@3.4.0 --save-dev --legacy-peer-deps --force
```

### Step 4: Verify Installation
```bash
npm list tailwindcss
```

You should see `tailwindcss@3.4.0` (not 4.1.18)

### Step 5: Test the Setup
```bash
npm start
```

If you see any errors, try:
```bash
npm install --legacy-peer-deps
```

## Alternative: Complete Clean Install (if above doesn't work)

If the above steps don't work, you may need to manually delete node_modules:

```bash
cd /Users/aditya/Documents/EMT/EasyMyTicket/frontend

# Try to delete node_modules (may require sudo)
sudo rm -rf node_modules package-lock.json

# Fix npm cache
sudo chown -R $(whoami) ~/.npm
npm cache clean --force

# Reinstall everything
npm install --legacy-peer-deps
```

## Verify Tailwind is Working

After fixing, test Tailwind by updating `src/App.tsx`:

```tsx
function App() {
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <h1 className="text-4xl font-bold text-blue-600">
        Tailwind CSS is working! 🎉
      </h1>
    </div>
  );
}
```

Then run `npm start` and check if styles are applied.
