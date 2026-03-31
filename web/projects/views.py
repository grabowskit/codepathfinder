from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.contrib import messages
from .models import PathfinderProject
from .forms import ProjectForm
from .utils import trigger_indexer_job, stop_indexer_job, check_and_update_project_status, delete_elasticsearch_index, get_es_client



class ProjectListView(LoginRequiredMixin, ListView):
    model = PathfinderProject
    template_name = 'projects/project_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        # Admin sees all
        if self.request.user.is_superuser:
            queryset = PathfinderProject.objects.all().select_related('user')
        else:
            # User sees own projects + projects shared with them
            from django.db.models import Q
            queryset = PathfinderProject.objects.filter(
                Q(user=self.request.user) | Q(shared_with=self.request.user)
            ).distinct()
        
        # Check and update status for each project
        for project in queryset:
            check_and_update_project_status(project)
            
        return queryset

class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = PathfinderProject
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    success_url = reverse_lazy('project_list')

    def get_success_url(self):
        if 'wizard' in self.request.GET:
            from django.urls import reverse
            return reverse('setup_wizard') + '?from=project'
        return str(self.success_url)

    def form_valid(self, form):
        from core.models import SystemSettings
        form.instance.user = self.request.user
        # Use system setting for default concurrency
        settings = SystemSettings.get_settings()
        form.instance.concurrency = settings.indexer_concurrency
        if 'save_run' in self.request.POST:
            form.instance.status = 'running'
            form.instance.save() # Save first to get ID
            success, msg = trigger_indexer_job(form.instance)
            if success:
                messages.success(self.request, 'Project saved and indexing job started.')
            else:
                form.instance.status = 'pending'
                form.instance.save()
                messages.error(self.request, f'Project saved but job failed to start: {msg}')
        else:
            form.instance.status = 'pending'
            messages.success(self.request, 'Project saved.')
        return super().form_valid(form)


from django.views.generic import UpdateView

class ProjectUpdateView(LoginRequiredMixin, UpdateView):
    model = PathfinderProject
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    success_url = reverse_lazy('project_list')

    def get_queryset(self):
        # Only allow editing own projects or if superuser
        if self.request.user.is_superuser:
            return PathfinderProject.objects.all()
        return PathfinderProject.objects.filter(user=self.request.user)

    def form_valid(self, form):
        if 'save_run' in self.request.POST:
            form.instance.status = 'running'
            form.instance.save()
            success, msg = trigger_indexer_job(form.instance)
            if success:
                messages.success(self.request, 'Project updated and indexing job started.')
            else:
                form.instance.status = 'pending'
                form.instance.save()
                messages.error(self.request, f'Project updated but job failed to start: {msg}')
        else:
            messages.success(self.request, 'Project updated successfully.')
        return super().form_valid(form)

class ProjectCloneView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)
        
        # Check permissions: Can clone if owner or shared_with or admin
        if not request.user.is_superuser and project.user != request.user and not project.shared_with.filter(id=request.user.id).exists():
            messages.error(request, "Permission denied.")
            return redirect('project_list')

        # Clone the project
        project.pk = None
        project.save()
        
        # Reset specific fields for the clone
        project.name = f"{project.name} (Clone)"
        project.status = 'pending'
        project.user = request.user # The cloner becomes the owner of the copy
        project.save()
        
        messages.success(request, f"Project cloned successfully as '{project.name}'.")
        return redirect('project_list')

from django.contrib.auth import get_user_model

class ProjectShareView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)
        if not request.user.is_superuser and project.user != request.user:
            messages.error(request, "Permission denied. Only the owner can share projects.")
            return redirect('project_list')
        
        # Get users available to share with (exclude owner and already shared)
        User = get_user_model()
        available_users = User.objects.exclude(pk=project.user.pk).exclude(pk__in=project.shared_with.all())
        
        return render(request, 'projects/project_share.html', {
            'project': project,
            'available_users': available_users
        })

    def post(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)
        if not request.user.is_superuser and project.user != request.user:
            messages.error(request, "Permission denied.")
            return redirect('project_list')

        action = request.POST.get('action')
        User = get_user_model()

        if action == 'add':
            user_id = request.POST.get('user_id')
            try:
                user_to_share = User.objects.get(pk=user_id)
                if user_to_share == request.user:
                    messages.warning(request, "You cannot share a project with yourself.")
                else:
                    project.shared_with.add(user_to_share)
                    messages.success(request, f"Project shared with {user_to_share.username}.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")
        
        elif action == 'remove':
            user_id = request.POST.get('user_id')
            try:
                user_to_remove = User.objects.get(pk=user_id)
                project.shared_with.remove(user_to_remove)
                messages.success(request, f"Removed access for {user_to_remove.username}.")
            except User.DoesNotExist:
                messages.error(request, "User not found.")

        return redirect('project_share', pk=pk)

class ProjectActionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)
        
        # Check permissions: Owner, Shared, or Admin
        # NOTE: Shared users currently have full control over actions (Run/Stop)
        is_owner = project.user == request.user
        is_shared = project.shared_with.filter(id=request.user.id).exists()
        is_admin = request.user.is_superuser
        
        if not (is_owner or is_shared or is_admin):
            messages.error(request, "Permission denied.")
            return redirect('project_list')

        action = request.POST.get('action')
        
        # Shared users are restricted to Read-Only (and Clone which is handled by ProjectCloneView)
        # They CANNOT Run, Stop, Enable, Disable, or Delete.
        if is_shared and not (is_owner or is_admin):
             messages.error(request, "Shared users have read-only access. You cannot perform this action.")
             return redirect('project_list')

        if action == 'run':
            project.status = 'running'
            project.save()
            success, msg = trigger_indexer_job(project)
            if success:
                messages.success(request, f"Indexing job started for {project.name}.")
                try:
                    from telemetry.counters import increment
                    increment('index_count')
                except Exception:
                    pass
            else:
                project.status = 'pending' # Revert status
                project.save()
                messages.error(request, f"Failed to start job: {msg}")
            return redirect('project_list')
        elif action == 'stop':
            success, msg = stop_indexer_job(project)
            if success:
                project.status = 'stopped' # Set to stopped
                project.save()
                messages.success(request, f"Project stopped: {msg}")
            else:
                # If job not found, we still want to reset the status so the user isn't stuck
                if "No running job found" in msg:
                    project.status = 'pending'
                    project.save()
                    messages.warning(request, f"Job not found in cluster. Status reset to Pending. (Original error: {msg})")
                else:
                    messages.warning(request, f"Could not stop job: {msg}")
            return redirect('project_list')
        elif action == 'reset':
            # Reset a failed/stuck project back to pending so it can be run again
            # Also cleanup any orphaned containers/jobs
            stop_indexer_job(project)  # Try to clean up any lingering jobs
            project.status = 'pending'
            project.save()
            messages.success(request, f"Project '{project.name}' has been reset. You can now edit settings and run it again.")
            return redirect('project_list')
        elif action == 'enable':
             # Only owner/admin should be able to enable/disable or delete
             if not (request.user.is_superuser or project.user == request.user):
                 messages.error(request, "Only the owner can delete or change status.")
                 return redirect('project_list')
             
             project.is_enabled = True
             project.save()
             messages.success(request, f"Project enabled for search.")
             return redirect('project_list')

        elif action == 'disable':
            if not (request.user.is_superuser or project.user == request.user):
                 messages.error(request, "Only the owner can delete or change status.")
                 return redirect('project_list')

            # Always attempt to stop running jobs when disabling, to ensure clean state
            stop_indexer_job(project)
            project.is_enabled = False
            project.save()
            messages.success(request, f"Project disabled.")
            return redirect('project_list')
        elif action == 'delete':
            if not (request.user.is_superuser or project.user == request.user):
                 messages.error(request, "Only the owner can delete functionality.")
                 return redirect('project_list')

            # Try to stop any running job first (just in case status is out of sync)
            stop_indexer_job(project)

            # Delete the Elasticsearch index associated with this project
            es_success, es_msg = delete_elasticsearch_index(project)
            if not es_success:
                messages.warning(request, f"Project deleted but Elasticsearch index cleanup failed: {es_msg}")

            project.delete()
            messages.success(request, "Project deleted successfully.")
            return redirect('project_list')


from django.http import JsonResponse
from kubernetes import client as k8s_client
import docker


class ProjectAPIKeysView(LoginRequiredMixin, View):
    """
    Manage API keys for a project.
    GET: Display API keys page with list of keys
    POST: Handle key generation and revocation
    """
    def get(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)

        # Check permissions: Only owner can manage API keys
        if not request.user.is_superuser and project.user != request.user:
            messages.error(request, "Permission denied. Only the project owner can manage API keys.")
            return redirect('project_list')

        # Retrieve new key from session and remove it (Flash message pattern)
        new_api_key = request.session.pop('new_api_key', None)
        new_api_key_label = request.session.pop('new_api_key_label', None)

        # Get all API keys for this project
        from .models import ProjectAPIKey
        api_keys = ProjectAPIKey.objects.filter(project=project).order_by('-created_at')

        return render(request, 'projects/project_api_keys.html', {
            'project': project,
            'api_keys': api_keys,
            'new_api_key': new_api_key,
            'new_api_key_label': new_api_key_label
        })

    def post(self, request, pk):
        project = get_object_or_404(PathfinderProject, pk=pk)

        # Check permissions: Only owner can manage API keys
        if not request.user.is_superuser and project.user != request.user:
            messages.error(request, "Permission denied. Only the project owner can manage API keys.")
            return redirect('project_list')

        action = request.POST.get('action')
        from .models import ProjectAPIKey

        if action == 'generate':
            label = request.POST.get('label', 'Unnamed Key').strip()
            if not label:
                label = 'Unnamed Key'

            # Generate new key
            api_key = ProjectAPIKey(
                project=project,
                label=label
            )
            plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()
            api_key.hashed_key = hashed_key
            api_key.prefix = prefix
            api_key.save()

            # Store plain key in session for one-time display
            request.session['new_api_key'] = plain_key
            request.session['new_api_key_label'] = label

            messages.success(request, f"API key '{label}' created successfully. Make sure to copy it now - you won't see it again!")
            return redirect('project_api_keys', pk=pk)

        elif action == 'revoke':
            key_id = request.POST.get('key_id')
            try:
                api_key = ProjectAPIKey.objects.get(pk=key_id, project=project)
                label = api_key.label
                api_key.delete()
                messages.success(request, f"API key '{label}' has been revoked.")
            except ProjectAPIKey.DoesNotExist:
                messages.error(request, "API key not found.")

            return redirect('project_api_keys', pk=pk)

        messages.error(request, "Invalid action.")
        return redirect('project_api_keys', pk=pk)


class GetJobLogsView(LoginRequiredMixin, View):
    """Fetch Kubernetes logs for running indexer jobs"""
    
    def get(self, request):
        try:
            from kubernetes import config as k8s_config
            
            # Load Kubernetes config
            try:
                try:
                    k8s_config.load_incluster_config()
                except:
                    k8s_config.load_kube_config()
                
                v1 = k8s_client.CoreV1Api()
                namespace = 'codepathfinder'
                
                # Get running pods with indexer-cli label
                pods = v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector='app=indexer-cli'
                )
                
                # Get active project IDs
                # Include projects shared with user
                from django.db.models import Q
                if request.user.is_superuser:
                    active_projects = PathfinderProject.objects.all().values_list('id', flat=True)
                else:
                    active_projects = PathfinderProject.objects.filter(
                        Q(user=request.user) | Q(shared_with=request.user)
                    ).values_list('id', flat=True)
                active_project_ids = set(active_projects)
                
                # Group pods by project
                project_pods = {}
                for pod in pods.items:
                    project_id = pod.metadata.labels.get('project-id')
                    if project_id and int(project_id) in active_project_ids:
                        pid = int(project_id)
                        if pid not in project_pods:
                            project_pods[pid] = []
                        project_pods[pid].append(pod)

                logs = []
                for project_id, pods_list in project_pods.items():
                    # Sort by creation timestamp (newest first)
                    pods_list.sort(key=lambda p: p.metadata.creation_timestamp, reverse=True)
                    latest_pod = pods_list[0]
                    
                    phase = latest_pod.status.phase
                    pod_name = latest_pod.metadata.name

                    if phase == 'Pending':
                        # Check for specific reasons (e.g., ContainerCreating)
                        reason = "Waiting for pod to be scheduled..."
                        if latest_pod.status.container_statuses:
                            for container in latest_pod.status.container_statuses:
                                if container.state.waiting:
                                    reason = f"{container.state.waiting.reason}: {container.state.waiting.message or ''}"
                                    break
                        
                        logs.append({
                            'pod': pod_name,
                            'message': f"[INFO] Job created. Status: {phase}. {reason}"
                        })
                    
                    elif phase in ['Running']:
                        try:
                            # Get last 50 lines of logs
                            pod_logs = v1.read_namespaced_pod_log(
                                name=pod_name,
                                namespace=namespace,
                                tail_lines=50
                            )
                            
                            if not pod_logs:
                                logs.append({
                                    'pod': pod_name,
                                    'message': f"[INFO] Pod is {phase}. Waiting for logs..."
                                })
                            else:
                                # Parse log lines
                                for line in pod_logs.split('\n'):
                                    if line.strip():
                                        logs.append({
                                            'pod': pod_name,
                                            'message': line.strip()
                                        })
                        except Exception as e:
                            logs.append({
                                'pod': pod_name,
                                'message': f'[WARN] Pod is {phase} but failed to fetch logs: {str(e)}'
                            })
            
            except Exception:
                # Fallback to local Docker logs
                client = docker.from_env()
                containers = client.containers.list(all=True, filters={"label": "app=indexer-cli"})
                
                logs = []
                for container in containers:
                    project_id = container.labels.get('project-id')
                    if not project_id:
                        continue
                        
                    try:
                        # Get last 50 lines
                        log_output = container.logs(tail=50).decode('utf-8')
                        
                        status = container.status
                        name = container.name
                        
                        if not log_output:
                             logs.append({
                                'pod': name,
                                'message': f"[INFO] Container is {status}. Waiting for logs..."
                            })
                        else:
                            for line in log_output.split('\n'):
                                if line.strip():
                                    logs.append({
                                        'pod': name,
                                        'message': line.strip()
                                    })
                    except Exception as e:
                         logs.append({
                            'pod': container.name,
                            'message': f'[WARN] Failed to fetch local logs: {str(e)}'
                        })
            
            # Reverse logs to show newest first
            logs.reverse()
            
            return JsonResponse({'logs': logs})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class GetProjectStatusesView(LoginRequiredMixin, View):
    """Fetch current status for all projects (for real-time UI updates)"""

    def get(self, request):
        from django.db.models import Q

        # Get projects user has access to
        if request.user.is_superuser:
            projects = PathfinderProject.objects.all()
        else:
            projects = PathfinderProject.objects.filter(
                Q(user=request.user) | Q(shared_with=request.user)
            ).distinct()

        # Check and update status for running/watching projects
        for project in projects.filter(status__in=['running', 'pending']):
            check_and_update_project_status(project)

        # Re-fetch projects to pick up progress fields written by check_and_update_project_status
        projects = projects.all()

        # Return current statuses
        statuses = {}
        for project in projects:
            statuses[project.pk] = {
                'status': project.status,
                'status_display': project.get_status_display(),
                'updated_at': project.updated_at.isoformat() if project.updated_at else None,
                'stage': project.current_stage or '',
                'progress_pct': project.progress_pct,
                'total_files': project.total_files,
                'stage_message': project.stage_message or '',
            }

        return JsonResponse({'statuses': statuses})


class GetIndexStatsView(LoginRequiredMixin, View):
    """Fetch Elasticsearch index stats for a project."""

    def get(self, request, pk):
        from django.db.models import Q

        # Verify access to the project
        if request.user.is_superuser:
            project = get_object_or_404(PathfinderProject, pk=pk)
        else:
            project = get_object_or_404(
                PathfinderProject.objects.filter(
                    Q(user=request.user) | Q(shared_with=request.user)
                ).distinct(),
                pk=pk
            )

        # Initialize response
        data = {
            'project_id': project.pk,
            'index_name': project.custom_index_name,
            'index_exists': False,
            'document_count': None,
            'size_mb': None,
            'health': None,
            'error': None,
        }

        if not project.custom_index_name:
            data['error'] = 'No index configured'
            return JsonResponse(data)

        try:
            es_client = get_es_client()
            if not es_client:
                data['error'] = 'Elasticsearch not configured'
                return JsonResponse(data)

            # Check if index exists
            if not es_client.indices.exists(index=project.custom_index_name):
                data['index_exists'] = False
                data['error'] = 'Index not found'
                return JsonResponse(data)

            data['index_exists'] = True

            # Get document count via count API (compatible with Elasticsearch Serverless)
            count_result = es_client.count(index=project.custom_index_name)
            data['document_count'] = count_result.get('count', 0)
            data['health'] = 'indexed'

        except Exception as e:
            data['error'] = f'Failed to fetch stats: {str(e)}'

        return JsonResponse(data)
