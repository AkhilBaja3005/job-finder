#!/bin/bash
# Oracle Cloud VM Auto-Setup Script for Job Finder Backend
set -e

echo "🚀 Updating system packages..."
sudo apt update && sudo apt upgrade -y

echo "📦 Installing core dependencies (Python, Git, Build tools, Curl)..."
sudo apt install -y python3-pip python3-venv git curl wget build-essential libssl-dev pkg-config

echo "📄 Installing Tectonic TeX Engine..."
if ! command -v tectonic &> /dev/null; then
    curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.tectonic-typesetting.github.io | sh
    sudo mv tectonic /usr/local/bin/
fi

echo "📂 Setting up project directory..."
cd ~
if [ ! -d "job-finder" ]; then
    git clone https://github.com/AkhilBaja3005/job-finder.git
fi

cd ~/job-finder/backend

echo "🐍 Creating Python Virtual Environment..."
python3 -m venv venv
source venv/bin/activate

echo "📥 Installing Python package dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🌐 Installing Playwright and Chromium browser binary dependencies..."
playwright install-deps
playwright install chromium

echo "⚙️ Setting up systemd background service..."
sudo cp ~/job-finder/deploy/jobfinder.service /etc/systemd/system/jobfinder.service
sudo systemctl daemon-reload
sudo systemctl enable jobfinder
sudo systemctl restart jobfinder

echo "🔓 Opening Port 8000 on iptables firewall..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save || true

echo "✅ Setup Complete! Job Finder backend is active and running!"
echo "Check status with: sudo systemctl status jobfinder"
