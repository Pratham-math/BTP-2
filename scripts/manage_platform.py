"""Explicit operator actions; never an HTTP route or a self-signup role choice."""
import argparse
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from server.database import AuditEvent, Job, Profile, make_engine, session_factory
from server.platform_settings import PlatformSettings


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant-role")
    grant.add_argument("user_id", type=UUID)
    grant.add_argument("role", choices=["student", "teacher", "administrator"])
    grant.add_argument("--reason", required=True)
    acknowledge = commands.add_parser('confirm-worker-stopped', help='Only after manually verifying the exact cancelled worker is stopped on its host')
    acknowledge.add_argument('job_id', type=UUID)
    acknowledge.add_argument('--reason', required=True)
    acknowledge.add_argument('--confirm-host-process-stopped', action='store_true', required=True)
    args = parser.parse_args()
    settings = PlatformSettings.from_env()
    engine = make_engine(settings.database_url)
    with session_factory(engine).begin() as db:
        if args.command == 'confirm-worker-stopped':
            job = db.scalar(select(Job).where(Job.id == str(args.job_id)).with_for_update(nowait=True))
            if not job or job.state != 'cancelled':
                raise SystemExit('Only an exact cancelled worker job may be acknowledged.')
            profile = db.get(Profile, job.owner_id)
            requests = db.scalars(select(Job).where(Job.owner_id == job.owner_id, Job.kind == 'erase_account')).all()
            if (not profile or profile.active or not any(any(x['id'] == job.id and x['fence'] == job.fence
                    for x in request.payload.get('await_workers', [])) for request in requests)):
                raise SystemExit('This worker is not awaited by an explicitly requested disabled-account erasure.')
            job.result = {**job.result, 'worker_stopped': True}
            db.add(AuditEvent(actor_id=profile.id, target_id=job.id, action='operator_worker_stop_confirmed',
                details={'reason': args.reason, 'fence': job.fence, 'via': 'host_operator_cli'}))
        else:
            profile = db.get(Profile, str(args.user_id))
            if not profile or not profile.active:
                raise SystemExit("This account must sign in and remain active before an operator can grant it a role.")
            previous, profile.privilege = profile.privilege, args.role
            db.add(AuditEvent(actor_id=profile.id, target_id=profile.id, action="operator_role_grant",
                              details={"previous": previous, "role": args.role, "reason": args.reason, "via": "host_operator_cli"}))
    engine.dispose()
    print("Requested operator action completed and audited.")


if __name__ == "__main__":
    main()
