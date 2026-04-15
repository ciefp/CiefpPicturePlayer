#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpPicturePlayer/main/installer.sh -O - | /bin/sh

######### Only This 2 lines to edit with new version ######
version='1.0'
changelog='\n- Initial release\n- Local, network and online picture viewer\n- SMB network shares support\n- ePicLoad for image scaling'
##############################################################

# Check if we should skip restart (for batch installations)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/CiefpPicturePlayer

if [ ! -d /usr/lib64 ]; then
	PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpPicturePlayer
else
	PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpPicturePlayer
fi

# Check package manager and OS type
if [ -f /var/lib/dpkg/status ]; then
	STATUS=/var/lib/dpkg/status
	OSTYPE=DreamOs
	PKG_UPDATE="apt-get update"
	PKG_INSTALL="apt-get install -y"
else
	STATUS=/var/lib/opkg/status
	OSTYPE=Dream
	PKG_UPDATE="opkg update"
	PKG_INSTALL="opkg install"
fi

echo ""
echo "============================================================"
echo "     CiefpPicturePlayer v$version Installer"
echo "============================================================"
echo ""

# Check Python version
if python --version 2>&1 | grep -q '^Python 3\.'; then
	echo "[OK] Python 3.x detected"
	PYTHON=PY3
	PACKAGE_SIX="python3-six"
	PACKAGE_REQUESTS="python3-requests"
else
	echo "[OK] Python 2.x detected"
	PYTHON=PY2
	PACKAGE_REQUESTS="python-requests"
fi

echo ""

# Function to install package if not exists
install_if_missing() {
	local pkg=$1
	local pkg_name=$2
	
	if grep -q "Package: $pkg" $STATUS 2>/dev/null; then
		echo "[OK] $pkg_name already installed"
		return 0
	else
		echo "[INSTALL] Installing $pkg_name..."
		$PKG_UPDATE > /dev/null 2>&1
		$PKG_INSTALL $pkg
		if [ $? -eq 0 ]; then
			echo "[OK] $pkg_name installed successfully"
			return 0
		else
			echo "[WARN] Failed to install $pkg_name"
			return 1
		fi
	fi
}

# Install python-six (only for Python 3)
if [ $PYTHON = "PY3" ]; then
	install_if_missing "$PACKAGE_SIX" "python3-six"
fi

echo ""

# Install python-requests (required for GitHub API and online content)
install_if_missing "$PACKAGE_REQUESTS" "python-requests"

echo ""

# Install cifs-utils (required for SMB network shares)
if command -v mount.cifs >/dev/null 2>&1; then
	echo "[OK] cifs-utils already installed"
else
	echo "[INSTALL] Installing cifs-utils (required for SMB network shares)..."
	$PKG_UPDATE > /dev/null 2>&1
	$PKG_INSTALL cifs-utils
	if [ $? -eq 0 ]; then
		echo "[OK] cifs-utils installed successfully"
	else
		echo "[WARN] Failed to install cifs-utils"
		echo "       Network shares may not work!"
	fi
fi

echo ""
echo "============================================================"
echo ""

# Remove tmp directory
[ -d $TMPPATH ] && rm -rf $TMPPATH

# Remove old plugin directory
[ -d $PLUGINPATH ] && rm -rf $PLUGINPATH

# Download and install plugin
mkdir -p $TMPPATH
cd $TMPPATH

echo "[DOWNLOAD] Downloading plugin..."

# Try to download main.tar.gz
if wget -q --no-check-certificate https://github.com/ciefp/CiefpPicturePlayer/archive/refs/heads/main.tar.gz; then
	echo "[OK] Download successful"
else
	echo "[ERROR] Failed to download plugin!"
	echo "       Please check internet connection and try again."
	exit 1
fi

echo "[EXTRACT] Extracting..."
tar -xzf main.tar.gz

echo "[INSTALL] Installing files..."
cp -r 'CiefpPicturePlayer-main/usr' '/'

cd
sleep 2

# Check if plugin installed correctly
if [ ! -d $PLUGINPATH ]; then
	echo "[ERROR] Plugin not installed correctly!"
	echo "       Please check the package structure."
	exit 1
fi

# Set permissions
chmod -R 755 $PLUGINPATH
echo "[OK] Permissions set"

# Cleanup
rm -rf $TMPPATH
sync

echo ""
echo "#########################################################"
echo "#           CiefpKingSat INSTALLED SUCCESSFULLY         #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
echo "#########################################################"

# REBOOT LOGIKA (Poštuje tvoj SKIP_REBOOT flag)
if [ "$SKIP_REBOOT" = "0" ]; then
    echo "#           Your device will RESTART Now                #"
    sleep 3
    killall -9 enigma2
else
    echo "#           Installation finished (No Reboot)           #"
fi