# Elasticsearch License Reset & Backup Automation Plan

## Objective
Automate the 30-day Elasticsearch license reset process so that users do not have to manually re-index all CodePathfinder projects every month. The automation will back up all indices before the reset and seamlessly restore them to the newly licensed cluster.

## Proposed Strategy
Use Elasticsearch's native **Snapshot/Restore API** in combination with Docker volumes.

---

## Instructions for the Implementing AI Agent

You need to execute the following three steps to fullfil this automation.

### 1. Update `docker-compose.yml`
We require a dedicated Docker volume for snapshots that survives the data deletion process. We map this new volume to `/usr/share/elasticsearch/snapshots` and expose it to Elasticsearch via the `path.repo` environment variable.

**Instructions:**
1. In the `elasticsearch` service `environment` section, append:
   `- path.repo=/usr/share/elasticsearch/snapshots`
2. In the `elasticsearch` service `volumes` section, append:
   `- elasticsearch_snapshots:/usr/share/elasticsearch/snapshots`
3. At the bottom of the file in the `volumes:` block, declare the new external volume:
   ```yaml
   elasticsearch_snapshots:
     external: true
     name: pathfinder_elasticsearch_snapshots
   ```

### 2. Create the Automation Script
Create an orchestrator script (`scripts/reset-elasticsearch.sh`) that automates the legacy manual procedure while adding backup/restore. Make sure to `chmod +x` it.

**Script Logic Flow:**
1. **Prerequisites**: Source the existing `ELASTICSEARCH_PASSWORD` from `.env` and create the snapshot volume internally: `docker volume create pathfinder_elasticsearch_snapshots`.
2. **Snapshot Initialization**: Send a `PUT /_snapshot/license_reset_backup` request with `type: fs` and `location: /usr/share/elasticsearch/snapshots`.
3. **Backup Execution**: Trigger `PUT /_snapshot/license_reset_backup/backup_$(date +%Y%m%d)?wait_for_completion=true` and wait for it to finish.
4. **Data Purge**: 
   - `docker compose down elasticsearch kibana`
   - `docker volume rm pathfinder_elasticsearch_data`
   - `docker volume create pathfinder_elasticsearch_data`
   - `docker compose up -d elasticsearch`
   - `sleep 30`
5. **Credentials Reset**:
   - Generate a new built-in elastic password: `elastic_password=$(docker compose exec elasticsearch bin/elasticsearch-reset-password -u elastic -b)`
   - Auto-update `.env` with the new password via regex/sed.
   - Auto-update Postgres settings using the Django shell (`docker compose exec web python manage.py shell`).
   - Generate a new Kibana Token and patch `docker-compose.yml` with it.
6. **Activate ML Tools**:
   - Start trial: `POST /_license/start_trial?acknowledge=true`
   - Deploy ELSER: `PUT /_inference/sparse_embedding/elser-2-elasticsearch`
7. **Restore the Snapshot**:
   - Re-register the snapshot repository (the cluster state was wiped).
   - Restore non-system indices (projects/chunks): `POST /_snapshot/license_reset_backup/{backup_id}/_restore` with body `{"indices": "*,-.*", "ignore_unavailable": true}`.
8. **Finalize**: 
   - Start/restart `kibana` and `web` containers.

### 3. Update Existing Documentation
Modify `docs/ELASTICSEARCH_LICENSE_RESET.md`.
- Replace the massive step-by-step Reset Procedure with simple instructions to execute `./scripts/reset-elasticsearch.sh`.
- Update the "What Gets Preserved vs. Lost" section to clarify that all Elasticsearch indices and code chunks are now natively preserved through automation.
