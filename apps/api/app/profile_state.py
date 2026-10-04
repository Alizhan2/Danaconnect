"""Live registration completeness; stored legacy flags do not grant admission."""

MENTOR_COMMITMENT_VERSION = "intake-3-6-months-v1"


def profile_complete(user):
    if user.role == "admin":
        return True
    base = bool((user.full_name or "").strip() and (user.city or "").strip()
                and len((user.bio or "").strip()) >= 10 and user.direction_ids)
    if user.role == "mentee":
        return base and user.birth_date is not None
    if user.role == "mentor":
        return (base and len((user.expertise or "").strip()) >= 10 and bool(user.evidence_urls)
                and bool((user.organization or "").strip()) and bool((user.phone or "").strip())
                and user.mentor_commitment is True and user.mentor_commitment_accepted_at is not None)
    return False


def admitted_profile(user):
    return bool(user.profile_completed and profile_complete(user))
