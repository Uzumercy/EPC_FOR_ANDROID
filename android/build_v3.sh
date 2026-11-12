#!/bin/bash
set -e
cd "$(dirname "$0")"
BT=~/android-sdk/build-tools/android-14
AJ=~/android-sdk/platforms/android-34/android.jar
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
rm -rf classes dex app-unsigned.apk app-aligned.apk epc-search-v3.apk
mkdir -p classes dex
$JAVA_HOME/bin/javac -encoding UTF-8 -source 8 -target 8 -cp "$AJ" -d classes $(find src -name '*.java')
$BT/d8 --lib "$AJ" --output dex $(find classes -name '*.class')
$BT/aapt package -f -M AndroidManifest.xml -A assets -I "$AJ" -F app-unsigned.apk
cp dex/classes.dex .
$BT/aapt add app-unsigned.apk classes.dex > /dev/null
rm classes.dex
$BT/zipalign -f -p 4 app-unsigned.apk app-aligned.apk
if [ ! -f debug.keystore ]; then
  $JAVA_HOME/bin/keytool -genkeypair -keystore debug.keystore -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=EPC Search,O=Personal,C=JP"
fi
$BT/apksigner sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android --out epc-search-v3.apk app-aligned.apk
$BT/apksigner verify --print-certs epc-search-v3.apk | head -3
ls -la epc-search-v3.apk
