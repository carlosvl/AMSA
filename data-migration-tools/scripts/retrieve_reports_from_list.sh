#!/bin/bash
# Retrieve reports from Alianza_Reports folder
# Usage: ./retrieve_reports_from_list.sh <org_alias> [reports_file.txt]

ORG_ALIAS=${1:-'AMSA-Royalty-Becky'}
REPORTS_FILE=${2:-''}

echo "=================================================================================="
echo "RETRIEVING REPORTS FROM ALIANZA_REPORTS FOLDER"
echo "Org: $ORG_ALIAS"
echo "=================================================================================="
echo ""

# If no file provided, try to get list from org
if [ -z "$REPORTS_FILE" ]; then
    echo "📥 Getting list of reports from org..."
    echo ""
    echo "Please run this command to get the report list:"
    echo "  sf data query --query \"SELECT DeveloperName FROM Report WHERE FolderName = 'Alianza_Reports' AND IsDeleted = false ORDER BY Name\" --target-org '$ORG_ALIAS' --result-format csv > reports_list.csv"
    echo ""
    echo "Then run this script again with the CSV file:"
    echo "  ./retrieve_reports_from_list.sh '$ORG_ALIAS' reports_list.csv"
    echo ""
    exit 0
fi

# Read report names from file
if [ ! -f "$REPORTS_FILE" ]; then
    echo "❌ File not found: $REPORTS_FILE"
    exit 1
fi

# Extract report names (skip header if CSV)
REPORTS=$(tail -n +2 "$REPORTS_FILE" 2>/dev/null | cut -d',' -f1 | grep -v '^$' || cat "$REPORTS_FILE" | grep -v '^$')

TOTAL=$(echo "$REPORTS" | wc -l | tr -d ' ')
echo "Found $TOTAL reports to retrieve"
echo ""

SUCCESS=0
FAILED=0
COUNT=0

for REPORT_NAME in $REPORTS; do
    COUNT=$((COUNT + 1))
    REPORT_NAME=$(echo "$REPORT_NAME" | tr -d '"' | tr -d ' ')
    
    if [ -z "$REPORT_NAME" ]; then
        continue
    fi
    
    echo "[$COUNT/$TOTAL] Retrieving: $REPORT_NAME"
    
    if sf project retrieve start --metadata "Report:Alianza_Reports/$REPORT_NAME" --target-org "$ORG_ALIAS" > /dev/null 2>&1; then
        echo "    ✅ Retrieved"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "    ❌ Failed"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=================================================================================="
echo "SUMMARY"
echo "=================================================================================="
echo "✅ Successful: $SUCCESS"
echo "❌ Failed: $FAILED"
echo ""
