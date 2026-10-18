"""CPU gates complement real Core↔Support HTTP/PG runner in TSupport."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jwt, pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from app.services import ticket_communications as tc, jitsi

@pytest.mark.asyncio
async def test_membership_is_required_even_for_superadmin():
    db=SimpleNamespace(get=AsyncMock(return_value=None))
    actor=SimpleNamespace(id=uuid.uuid4(),mail_only=False,is_superadmin=True)
    with pytest.raises(HTTPException) as error:
        await tc.access(db,uuid.uuid4(),actor,uuid.uuid4())
    assert error.value.status_code==403

@pytest.mark.asyncio
async def test_legacy_and_mixed_are_never_promoted_to_private():
    for purpose,audience in [(None,'mixed'),('support_staff','mixed'),(None,'internal')]:
        room=SimpleNamespace(scope_ticket_id=uuid.uuid4(),scope_purpose=purpose,scope_product='support',audience=audience)
        with pytest.raises(HTTPException) as error:
            await tc.assert_staff_room(None,room,SimpleNamespace(id=uuid.uuid4()))
        assert error.value.status_code==404

@pytest.mark.asyncio
async def test_explicit_invite_never_falls_back_to_superadmin(monkeypatch):
    room=SimpleNamespace(is_active=True,id=uuid.uuid4(),company_id=uuid.uuid4(),scope_ticket_id=uuid.uuid4(),scope_purpose='support_staff',scope_product='support',audience='internal')
    db=SimpleNamespace(scalar=AsyncMock(return_value=None))
    proof=AsyncMock(return_value={'canStaffChat':True});monkeypatch.setattr(tc,'access',proof)
    user=SimpleNamespace(id=uuid.uuid4(),is_superadmin=True)
    with pytest.raises(HTTPException):await tc.assert_staff_room(db,room,user)
    proof.assert_not_awaited()
    await tc.assert_staff_room(db,room,user,require_member=False);proof.assert_awaited_once()

def test_video_short_participant_token_and_ordinary_legacy_hours(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    monkeypatch.setattr(jitsi,'_private_key',lambda:pem)
    for options,ttl in [({'moderator':False,'ttl_seconds':120},120),({},4*3600)]:
        claims=jwt.decode(jitsi.sign_token('private-room','Customer',**options),key.public_key(),algorithms=['RS256'],audience='jitsi')
        assert claims['exp']-claims['iat']==ttl
        assert claims['context']['user']['moderator']==options.get('moderator',True)
        assert claims['room']=='private-room'
    monkeypatch.setattr(jitsi,'_private_key',lambda:None)
    assert jitsi.sign_token('private-room','Name',ttl_seconds=120) is None

@pytest.mark.parametrize("enabled,key",[(False,""),(True,""),(True,"not-valid-base64")])
def test_private_media_capability_is_fail_closed_before_any_trace(monkeypatch,enabled,key):
    from app.routers.ticket_communications_router import require_private_video
    monkeypatch.setattr(jitsi.settings,'jitsi_ticket_private_enabled',enabled)
    monkeypatch.setattr(jitsi.settings,'jitsi_signing_key',key)
    with pytest.raises(HTTPException) as error:
        require_private_video()
    assert error.value.status_code==503
    assert error.value.detail['code']=='private_video_unavailable'

@pytest.mark.asyncio
@pytest.mark.parametrize("raises",[False,True])
async def test_sign_failure_does_not_record_video_history(monkeypatch,raises):
    from app.routers import ticket_communications_router as router
    cid,tid=uuid.uuid4(),uuid.uuid4()
    proof=AsyncMock(return_value={"canVideo":True,"canStaffChat":True})
    monkeypatch.setattr(router,"access",proof)
    monkeypatch.setattr(router,"_scope",AsyncMock(return_value=cid))
    monkeypatch.setattr(router,"require_private_video",lambda:None)
    def fail(*args,**kwargs):
        if raises:raise ValueError("test signing failure")
        return None
    monkeypatch.setattr(jitsi,"sign_token",fail)
    db=SimpleNamespace(execute=AsyncMock(),scalar=AsyncMock(return_value=SimpleNamespace(room="stable-ticket-room")),commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await router.ticket_video(tid,router.TicketCompany(supportCompanyId=uuid.uuid4()),SimpleNamespace(id=uuid.uuid4(),name="Actor"),db)
    assert error.value.status_code==503
    assert error.value.detail["code"]=="private_video_unavailable"
    assert all("event" not in call.kwargs for call in proof.await_args_list)

@pytest.mark.asyncio
@pytest.mark.parametrize("count,status",[(0,404),(2,409)])
async def test_missing_or_ambiguous_canonical_map_never_chooses_a_tenant(count,status):
    from app.routers.ticket_communications_router import _scope
    values=[uuid.uuid4() for _ in range(count)]
    result=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:values))
    db=SimpleNamespace(execute=AsyncMock(return_value=result))
    with pytest.raises(HTTPException) as error:await _scope(db,uuid.uuid4())
    assert error.value.status_code==status

@pytest.mark.asyncio
async def test_inactive_ticket_room_does_not_deliver_even_with_still_valid_support_acl(monkeypatch):
    room=SimpleNamespace(id=uuid.uuid4(),is_active=False,company_id=uuid.uuid4(),scope_ticket_id=uuid.uuid4(),scope_purpose='support_staff',scope_product='support',audience='internal')
    proof=AsyncMock(return_value={'canStaffChat':True});monkeypatch.setattr(tc,'access',proof)
    db=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    assert await tc.recipient_allowed(db,room,uuid.uuid4()) is False
    proof.assert_not_awaited()
