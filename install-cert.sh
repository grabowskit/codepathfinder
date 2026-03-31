#!/bin/bash

# Install mkcert CA certificate to system keychain
# This will prompt for your password

CA_PATH="$HOME/Library/Application Support/mkcert/rootCA.pem"

if [ ! -f "$CA_PATH" ]; then
    echo "❌ CA certificate not found at $CA_PATH"
    exit 1
fi

echo "🔐 Installing mkcert CA certificate..."
echo "You will be prompted for your password to install to the System keychain"
echo ""

sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CA_PATH"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Certificate installed successfully!"
    echo "You can now access https://localhost:8443 without certificate warnings"
else
    echo ""
    echo "❌ Installation failed. Please try the manual method below."
fi
