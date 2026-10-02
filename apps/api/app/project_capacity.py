"""A team collaborator and a current mentee occupy one shared project seat."""
from sqlalchemy import select, union
from app.models import Participation, ProjectMember


def project_occupant_ids(db, project):
    participation = select(Participation.mentee_id).where(Participation.project_id == project.id,
        Participation.status.in_(["active", "paused"]))
    collaborators = select(ProjectMember.user_id).where(ProjectMember.project_id == project.id,
        ProjectMember.member_role == "collaborator", ProjectMember.user_id != project.owner_id)
    if project.mentor_id:
        collaborators = collaborators.where(ProjectMember.user_id != project.mentor_id)
    return set(db.scalars(union(participation, collaborators)).all())


def project_occupied(db, project):
    return len(project_occupant_ids(db, project))
