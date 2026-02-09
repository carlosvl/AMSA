#!/bin/bash
# Retrieve all 143 reports from Alianza_Reports folder

ORG_ALIAS='AMSA-Royalty-Becky'
REPORTS_FILE='/tmp/clean_reports.txt'

echo "=================================================================================="
echo "RETRIEVING ALL REPORTS FROM ALIANZA_REPORTS FOLDER"
echo "Org: $ORG_ALIAS"
echo "=================================================================================="
echo ""

# Get clean list of reports
echo "📥 Getting list of reports..."
sf data query --query "SELECT DeveloperName FROM Report WHERE FolderName = 'Alianza Reports' AND IsDeleted = false ORDER BY Name" --target-org "$ORG_ALIAS" --result-format csv 2>/dev/null | grep -E "^[A-Za-z0-9_]+$" | grep -v "DeveloperName" > "$REPORTS_FILE"

TOTAL=$(wc -l < "$REPORTS_FILE" | tr -d ' ')
echo "  ✅ Found $TOTAL reports"
echo ""

SUCCESS=0
FAILED=0
COUNT=0

echo "🔄 Retrieving reports... (this may take a while)"
echo ""

while IFS= read -r REPORT_NAME; do
    COUNT=$((COUNT + 1))
    REPORT_NAME=$(echo "$REPORT_NAME" | tr -d '"' | tr -d ' ')
    
    if [ -z "$REPORT_NAME" ]; then
        continue
    fi
    
    # Show progress every 10 reports
    if [ $((COUNT % 10)) -eq 0 ]; then
        echo "[$COUNT/$TOTAL] Progress: $COUNT reports processed..."
    fi
    
    # Retrieve the report (suppress stderr to avoid log file errors)
    if sf project retrieve start --metadata "Report:Alianza_Reports/$REPORT_NAME" --target-org "$ORG_ALIAS" 2>/dev/null | grep -q "Retrieved"; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done < "$REPORTS_FILE"

echo ""
echo "=================================================================================="
echo "SUMMARY"
echo "=================================================================================="
echo "✅ Successful: $SUCCESS"
echo "❌ Failed: $FAILED"
echo ""
echo "Reports are saved to: force-app/main/default/reports/Alianza_Reports/"
echo ""
