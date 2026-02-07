#!/bin/bash
# Fix npm permission issues and Tailwind CSS version

echo "🔧 Fixing npm permission issues and Tailwind CSS..."

# Step 1: Fix npm cache permissions
echo "Step 1: Fixing npm cache permissions..."
sudo chown -R $(whoami) ~/.npm

# Step 2: Clean npm cache
echo "Step 2: Cleaning npm cache..."
npm cache clean --force

# Step 3: Navigate to frontend directory
cd "$(dirname "$0")"

# Step 4: Force install correct Tailwind version
echo "Step 3: Installing Tailwind CSS v3.4.0..."
npm install tailwindcss@3.4.0 --save-dev --legacy-peer-deps --force

# Step 5: Verify installation
echo "Step 4: Verifying installation..."
npm list tailwindcss

echo ""
echo "✅ Fix complete! Run 'npm start' to test."
echo ""
echo "If you still see errors, try:"
echo "  npm install --legacy-peer-deps"
