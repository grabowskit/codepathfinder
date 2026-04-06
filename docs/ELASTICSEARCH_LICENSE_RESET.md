# Elasticsearch License Reset Procedure

## Overview
Elasticsearch's trial license expires after 30 days. When it expires, ML features (including ELSER) become unavailable, blocking all indexing and search functionality. This document describes how to reset Elasticsearch to get a fresh trial license.

**Last Reset**: April 2, 2026
**Next Expected Expiration**: May 2, 2026

---

## Symptoms of Expired License

When the trial license expires, you'll see:

1. **Authentication errors** from Elasticsearch (401/403)
2. **Search failures** in CodePathfinder web UI
3. **MCP tools failing** to access indices
4. **Cannot index new projects** - ELSER model unavailable
5. **"license is non-compliant for [security]"** errors in logs

### Check License Status

```bash
curl -u "elastic:${ELASTICSEARCH_PASSWORD}" "http://localhost:9200/_xpack?pretty" | grep -A 5 '"license"'
```

Look for `"status": "expired"`.

---

## Reset Procedure

### Step 1: Stop and Remove Elasticsearch Data

```bash
cd /path/to/pathfinder

# Stop ES and Kibana
docker compose down elasticsearch kibana

# Delete the ES data volume
docker volume rm pathfinder_elasticsearch_data

# Recreate fresh volume
docker volume create pathfinder_elasticsearch_data
```

### Step 2: Start Elasticsearch

```bash
# Start ES with fresh volume
docker compose up -d elasticsearch

# Wait 30 seconds for startup
sleep 30
```

### Step 3: Reset Elastic User Password

```bash
# Generate new password
docker compose exec elasticsearch bin/elasticsearch-reset-password -u elastic -b

# Example output:
# Password for the [elastic] user successfully reset.
# New value: -M0FcIVCthrCSPN4O8JQ
```

**Save this password!** You'll need it in the next steps.

### Step 4: Update Configuration Files

Update the new password in **THREE** places:

#### 4a. Update `.env`

```bash
# Edit .env file
nano .env

# Update this line:
ELASTICSEARCH_PASSWORD=NEW_PASSWORD_HERE
```

#### 4b. Update Database Settings

```bash
docker compose exec web python manage.py shell -c "
from core.models import SystemSettings
import os

settings = SystemSettings.objects.first()
settings.elasticsearch_password = os.getenv('ELASTICSEARCH_PASSWORD')
settings.save()
print('✅ Updated SystemSettings')
"
```

#### 4c. Update Kibana Config

```bash
# Create new Kibana service account token
NEW_TOKEN=$(curl -s -X POST -u "elastic:NEW_PASSWORD_HERE" \
  'http://localhost:9200/_security/service/elastic/kibana/credential/token/kibana-token' \
  -H 'Content-Type: application/json' | jq -r '.token.value')

echo "New token: $NEW_TOKEN"

# Edit docker-compose.yml
nano docker-compose.yml

# Update this line in kibana service:
# - ELASTICSEARCH_SERVICEACCOUNTTOKEN=NEW_TOKEN_HERE
```

### Step 5: Start Trial License

```bash
curl -s -X POST -u "elastic:NEW_PASSWORD_HERE" \
  'http://localhost:9200/_license/start_trial?acknowledge=true&pretty'

# Expected output:
# {
#   "acknowledged" : true,
#   "trial_was_started" : true,
#   "type" : "trial"
# }
```

### Step 6: Deploy ELSER Model

```bash
# Create ELSER inference endpoint (takes ~30 seconds)
curl -s -X PUT -u "elastic:NEW_PASSWORD_HERE" \
  'http://localhost:9200/_inference/sparse_embedding/elser-2-elasticsearch' \
  -H 'Content-Type: application/json' \
  -d '{
    "service": "elasticsearch",
    "service_settings": {
      "num_allocations": 1,
      "num_threads": 1,
      "model_id": ".elser_model_2"
    }
  }'

# Wait for deployment
sleep 30

# Verify ELSER is running
curl -s -u "elastic:NEW_PASSWORD_HERE" \
  'http://localhost:9200/_ml/trained_models/.elser_model_2/_stats?pretty' \
  | grep -A 3 '"state"'

# Should show: "state" : "started"
```

### Step 7: Restart Services

```bash
# Recreate web container to pick up new password
docker compose up -d web

# Restart Kibana with new token
docker compose up -d kibana

# Reload nginx
docker compose exec nginx nginx -s reload
```

### Step 8: Verify Everything Works

```bash
# Test ES connection
docker compose exec web python manage.py shell -c "
from elasticsearch import Elasticsearch
import os

es = Elasticsearch(
    ['http://elasticsearch:9200'],
    basic_auth=('elastic', os.getenv('ELASTICSEARCH_PASSWORD')),
    verify_certs=False
)

health = es.cluster.health()
print(f'✅ ES Connected: {health[\"status\"]}')

inference = es.inference.get(inference_id='elser-2-elasticsearch')
print(f'✅ ELSER Ready: {inference[\"endpoints\"][0][\"service_settings\"][\"model_id\"]}')
"
```

Expected output:
```
✅ ES Connected: green
✅ ELSER Ready: .elser_model_2
```

---

## What Gets Preserved vs. Lost

### ✅ Preserved (Survives Reset)
- PostgreSQL database (projects, users, settings)
- Docker configuration files
- Application code
- Other container data (MongoDB, Meilisearch)

### ❌ Lost (Must Be Recreated)
- **All Elasticsearch indices** - including project code indices
- **All indexed code** - must re-index all projects
- Kibana dashboards and saved objects
- ES index patterns and templates
- Custom analyzers and mappings

**Important**: After reset, all projects will need to be re-indexed from the CodePathfinder UI.

---

## Quick Reference: Key Commands

### Check License Expiration Date
```bash
curl -s -u "elastic:${ELASTICSEARCH_PASSWORD}" \
  "http://localhost:9200/_xpack?pretty" | \
  jq -r '.license.expiry_date_in_millis' | \
  awk '{print strftime("%Y-%m-%d %H:%M:%S", $1/1000)}'
```

### Check ELSER Status
```bash
curl -s -u "elastic:${ELASTICSEARCH_PASSWORD}" \
  "http://localhost:9200/_ml/trained_models/.elser_model_2/_stats?pretty" | \
  grep '"state"'
```

### List All Indices
```bash
curl -s -u "elastic:${ELASTICSEARCH_PASSWORD}" \
  "http://localhost:9200/_cat/indices?v&s=index"
```

### Test Connection from Web Container
```bash
docker compose exec web python -c "
from elasticsearch import Elasticsearch
import os
es = Elasticsearch(['http://elasticsearch:9200'],
                   basic_auth=('elastic', os.getenv('ELASTICSEARCH_PASSWORD')))
print(es.cluster.health())
"
```

---

## Troubleshooting

### Issue: "Trial was already activated" Error

**Cause**: You can only activate a trial license once per cluster.

**Solution**: This is expected if you're resetting. The trial is automatically activated on first startup of a fresh cluster. Proceed to ELSER deployment.

---

### Issue: Kibana Shows "elasticsearch service is unavailable"

**Cause**: Kibana can't authenticate to ES (invalid service account token).

**Solution**:
1. Create new service account token (Step 4c above)
2. Update `docker-compose.yml`
3. Restart: `docker compose up -d kibana`

---

### Issue: ELSER Deployment Timeout

**Cause**: Model download/deployment takes time, especially first time.

**Solution**: Wait 1-2 minutes, then check status:
```bash
curl -s -u "elastic:${ELASTICSEARCH_PASSWORD}" \
  "http://localhost:9200/_inference/elser-2-elasticsearch?pretty"
```

If still not ready, check ES logs:
```bash
docker compose logs elasticsearch --tail=50
```

---

### Issue: Web App Can't Connect After Reset

**Cause**: Password not updated in all three places.

**Solution**: Verify password in:
1. `.env` file
2. `core.SystemSettings` database table
3. Environment variable in web container

Check with:
```bash
# Check .env
grep ELASTICSEARCH_PASSWORD .env

# Check database
docker compose exec web python manage.py shell -c "
from core.models import SystemSettings
print(SystemSettings.objects.first().elasticsearch_password[:10])
"

# Check container env
docker compose exec web printenv ELASTICSEARCH_PASSWORD
```

---

## Automation Considerations

For future automation, consider:

1. **Script the entire process** into `scripts/reset-elasticsearch.sh`
2. **Schedule reminders** 5 days before expiration
3. **Back up critical indices** before reset (if needed)
4. **Use Elastic Cloud** instead (avoid trial limitations)
5. **Track expiration date** in project documentation

---

## Alternative: Elastic Cloud

To avoid monthly resets, consider using Elastic Cloud:

**Pros**:
- No trial expiration
- ML features always available
- Managed updates and backups
- Better performance

**Cons**:
- Monthly cost (~$95/month for basic tier)
- Requires cloud account setup
- Slight latency vs. local

**Setup**: https://cloud.elastic.co/

---

## Checklist

Use this checklist when performing the reset:

- [ ] Note current license expiration date
- [ ] Stop Elasticsearch and Kibana
- [ ] Delete ES data volume
- [ ] Start Elasticsearch
- [ ] Reset elastic user password (save it!)
- [ ] Update `.env` with new password
- [ ] Update database SystemSettings
- [ ] Create new Kibana service token
- [ ] Update `docker-compose.yml` with new token
- [ ] Start trial license
- [ ] Deploy ELSER model
- [ ] Verify ELSER is "started"
- [ ] Restart web and kibana containers
- [ ] Test ES connection from web app
- [ ] Access Kibana at http://localhost:5601
- [ ] Update this document with new expiration date
- [ ] Re-index critical projects from UI

---

## Support

If issues persist after following this guide:

1. Check logs: `docker compose logs elasticsearch kibana web`
2. Verify all three password locations match
3. Ensure trial license is active
4. Confirm ELSER deployment is "fully_allocated"
5. Test ES connection directly with curl

For questions, see: `docs/DEPLOYMENT.md` or project README.
