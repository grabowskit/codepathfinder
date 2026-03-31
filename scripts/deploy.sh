#!/bin/bash
set -e

# Configuration — update these to match your GCP project
PROJECT_ID="${GCP_PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
REPO="codepathfinder"
IMAGE_NAME="web"
NAMESPACE="codepathfinder"
DEPLOYMENT="codepathfinder"

# Get version from argument or use timestamp
if [ -z "$1" ]; then
    VERSION="v$(date +%Y%m%d%H%M%S)"
else
    VERSION="$1"
fi

FULL_IMAGE_PATH="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$IMAGE_NAME:$VERSION"

echo "🚀 Starting deployment for version $VERSION..."

# 1. Build Docker Image
echo "📦 Building Docker image..."
docker build --platform linux/amd64 -f Dockerfile.prod -t "$FULL_IMAGE_PATH" .

# 2. Push to Artifact Registry
echo "⬆️ Pushing image to Artifact Registry..."
docker push "$FULL_IMAGE_PATH"

# 3. Update Kubernetes Deployment
echo "🔄 Updating Kubernetes deployment..."
kubectl set image "deployment/$DEPLOYMENT" "$IMAGE_NAME=$FULL_IMAGE_PATH" -n "$NAMESPACE"

# 4. Wait for Rollout
echo "⏳ Waiting for rollout to complete..."
kubectl rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE"

# 5. Verify migrations are applied
echo "🔄 Checking migration status..."
# Get a running web pod (exclude jobs/not-ready pods)
POD=$(kubectl get pod -n "$NAMESPACE" -l "app=$DEPLOYMENT,!job-name" --field-selector=status.phase=Running -o jsonpath="{.items[0].metadata.name}")

if [ -n "$POD" ]; then
    echo "   Checking migrations on $POD..."
    kubectl exec "$POD" -n "$NAMESPACE" -c web -- python manage.py migrate --check && \
        echo "✅ All migrations applied." || \
        echo "⚠️ Unapplied migrations detected — run: kubectl exec $POD -n $NAMESPACE -c web -- python manage.py migrate"
else
    echo "⚠️ Could not find running pod to check migrations!"
fi

echo "✅ Deployment of $VERSION complete!"
echo "   Image: $FULL_IMAGE_PATH"

echo "🎉 All steps finished successfully!"
