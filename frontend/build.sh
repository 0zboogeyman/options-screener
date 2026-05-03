#!/bin/bash
# 构建并复制 static 文件到 standalone
set -e

echo "Building Next.js..."
npm run build

echo "Copying static and server files to standalone..."
cp -r .next/static .next/standalone/.next/
cp -r .next/server .next/standalone/.next/
cp -r public .next/standalone/

echo "Build complete! All files copied to standalone."
echo "Run: pm2 restart spread-finder-web"
