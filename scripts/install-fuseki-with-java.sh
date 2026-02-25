#!/bin/bash
# install-fuseki-with-java.sh
# Install Java + Fuseki in one go

set -e

echo "=== Installing Java + Apache Jena Fuseki ==="
echo ""

# Step 1: Check if Java is installed
echo "🔍 Checking for Java..."
if command -v java &> /dev/null; then
    echo "✅ Java already installed:"
    java -version
    JAVA_OK=true
else
    echo "❌ Java not found. Installing OpenJDK 17..."
    sudo apt-get update -qq
    sudo apt-get install -y openjdk-17-jdk-headless
    echo "✅ Java installed:"
    java -version
    JAVA_OK=true
fi

echo ""

# Step 2: Install Fuseki (if not already done)
cd /opt

if [ -d "apache-jena-fuseki-4.10.0" ]; then
    echo "✅ Fuseki already extracted"
    ls -lh apache-jena-fuseki-4.10.0/
else
    echo "📦 Fuseki not yet extracted. Extracting now..."
    if [ -f "apache-jena-fuseki-4.10.0.tar.gz" ]; then
        sudo tar xzf apache-jena-fuseki-4.10.0.tar.gz
        sudo ln -sf apache-jena-fuseki-4.10.0 fuseki
        sudo chown -R th:th fuseki
        echo "✅ Extraction complete"
    else
        echo "❌ Downloaded tarball not found!"
        echo "Run: bash /home/th/repos/outremer/scripts/install-fuseki.sh"
        exit 1
    fi
fi

echo ""

# Step 3: Create data directory
echo "📁 Creating data directory..."
mkdir -p ~/fuseki-data
chown th:th ~/fuseki-data
echo "✅ Created ~/fuseki-data/"

# Step 4: Update startup script
echo "📝 Updating startup script..."
cat <<'STARTSCRIPT' > ~/start-fuseki.sh
#!/bin/bash
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH=$JAVA_HOME/bin:$PATH
cd /opt/fuseki
export FUSEKI_HOME=/opt/fuseki
export FUSEKI_BASE=$HOME/fuseki-data
./fuseki-server --mem --port 3030 /outremer
STARTSCRIPT

chmod +x ~/start-fuseki.sh
echo "✅ Startup script updated"

echo ""
echo "========================================="
echo "✅ Installation Complete!"
echo "========================================="
echo ""
echo "🚀 Start Fuseki:"
echo "  ~/start-fuseki.sh"
echo ""
echo "🌐 Access: http://194.13.80.183:3030"
echo ""
echo "💡 To run in background:"
echo "  nohup ~/start-fuseki.sh > ~/fuseki.log 2>&1 &"
echo "  (Then check: tail -f ~/fuseki.log)"
echo ""
