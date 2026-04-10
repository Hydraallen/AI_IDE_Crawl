#!/bin/bash
# Browsertrix Crawl Script for AI Coding Tools Crawl
# Usage: ./crawl.sh [collection-name]

COLLECTION_NAME=${1:-"crawl-$(date +%Y%m%d)"}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/browsertrix-config-simple.yaml"
OUTPUT_DIR="$SCRIPT_DIR/crawls"

echo "=========================================="
echo "AI Coding Tools Web Archival Crawl"
echo "=========================================="
echo "Collection: $COLLECTION_NAME"
echo "Config: $CONFIG_FILE"
echo "Output: $OUTPUT_DIR"
echo "=========================================="

docker run --rm \
  -v "$OUTPUT_DIR:/crawls" \
  -v "$CONFIG_FILE:/config/browsertrix-config.yaml:ro" \
  webrecorder/browsertrix-crawler:latest \
  crawl \
  --config /config/browsertrix-config.yaml \
  --collection "$COLLECTION_NAME" \
  --generateWACZ \
  --statsFilename /crawls/crawl-stats.json

echo ""
echo "=========================================="
echo "Crawl Complete!"
echo "=========================================="
echo "WACZ file: $OUTPUT_DIR/collections/$COLLECTION_NAME/$COLLECTION_NAME.wacz"
echo "WARC files: $OUTPUT_DIR/collections/$COLLECTION_NAME/archive/"
echo ""
echo "To view: Open https://replayweb.page/ and load the WACZ file"
echo "=========================================="
