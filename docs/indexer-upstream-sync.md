# Indexer Upstream Sync Analysis

## Summary

Analysis of differences between:
- **Fork**: `./indexer`
- **Upstream**: `https://github.com/elastic/semantic-code-search-indexer`

## Changes Applied in This Sync

### 1. Bash Language Support (NEW)
- Added `src/languages/bash.ts` from upstream
- Added `tree-sitter-bash` dependency to package.json
- Added `LANG_BASH` constant to constants.ts
- Added bash import/config to `src/languages/index.ts`

## Major Upstream Features NOT Yet Merged

### 1. Locations Index (`_locations`)
The upstream has added a significant new feature - a separate `_locations` index for tracking file locations. This involves:
- New `createLocationsIndex()` function
- New `deleteLocationsIndex()` function
- New `LocationDocument` type
- Integration with bulk indexing to write locations

**Files affected**: `src/utils/elasticsearch.ts` (1202 lines in upstream vs 477 in fork)

**Recommendation**: This is a major architectural change. Consider merging in a separate PR after stabilizing current indexing.

### 2. Worker Backpressure Fix (CRITICAL)
The upstream fixed a critical bug in `indexer_worker.ts`:
- Fixed backpressure calculation to use `size + pending` instead of just `size`
- Added proper handling when queue is empty but tasks are in-flight
- Improved retry/requeue handling for partial bulk failures

**Files affected**: `src/utils/indexer_worker.ts`

**Recommendation**: Merge this fix - it likely resolves some of the indexing issues we've seen.

### 3. Queue Improvements
- Enhanced `sqlite_queue.ts` with better stats caching
- Improved OTEL metrics export handling

### 4. Vitest Migration
Upstream migrated from Jest to Vitest. The fork still uses Jest.

**Recommendation**: Low priority - Jest works fine. Consider migrating later.

---

## Fork Customizations to Contribute Back to Upstream

### PR 1: SQL/dbt Parser Support (HIGH VALUE)

**Branch**: `feature/sql-dbt-parser`

**Files to include**:
```
src/languages/sql.ts                      (NEW - 22 lines)
src/utils/parser.ts                       (SQL methods, lines 553-1104)
src/utils/constants.ts                    (LANG_SQL, PARSER_TYPE_SQL)
tests/parser.test.ts                      (SQL test section, lines 908-1098)
tests/fixtures/sql_dbt_model.sql          (NEW)
tests/fixtures/sql_dbt_macro.sql          (NEW)
tests/fixtures/sql_pure.sql               (NEW)
```

**Features**:
- dbt `ref()`, `source()`, `macro()` extraction
- CTE (Common Table Expression) chunking
- CREATE TABLE/VIEW/FUNCTION detection
- Multi-dialect support (BigQuery, Snowflake, Databricks, Redshift, DuckDB)

### PR 2: Directory Metadata Fields (MEDIUM VALUE)

**Branch**: `feature/directory-metadata`

**Files to include**:
```
src/utils/parser.ts                       (extractDirectoryInfo function, lines 32-55)
src/utils/elasticsearch.ts                (index mapping additions, lines 115-117)
```

**New fields added to CodeChunk**:
- `directoryPath`: Full path (e.g., "src/components/auth")
- `directoryName`: Immediate directory name
- `directoryDepth`: Depth from repo root

### PR 3: Handlebars Support (LOWER VALUE)

**Branch**: `feature/handlebars-parser`

**Files to include**:
```
src/languages/handlebars.ts               (NEW)
docs/HANDLEBARS_SETUP.md                  (NEW)
```

Uses custom parser (tree-sitter-glimmer has build issues).

---

## Next Steps

1. **Immediate**: Test the bash language support addition
2. **High Priority**: Port the worker backpressure fix from upstream
3. **Medium Priority**: Evaluate locations index feature for future merge
4. **Ongoing**: Prepare PRs for SQL/dbt, directory metadata, and handlebars to upstream
