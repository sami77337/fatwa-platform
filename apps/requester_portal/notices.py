"""Short-lived PRG receipt, never a capability, answer cache or reading receipt."""

import json
from hmac import compare_digest

from django.views.decorators.debug import sensitive_variables

from apps.casework_web import requester_workspace as workspace

COOKIE = "fatwa_portal_notice"
SALT = "fatwa.portal.notice.v1"
MESSAGES = {
    "reply": "حُفظ ردك ضمن القضية وأُعيدت للمراجعة. لم يُرسل جواب خارجي.",
    "reply_file": "حُفظ ردك ومرفقه معًا ضمن القضية وأُعيدت للمراجعة.",
    "file": "حُفظ المرفق ضمن القضية وأُعيدت للمراجعة.",
    "review": "حُفظ طلب مراجعة أمان الوصول للفريق؛ لم يُبطل الرمز بهذه الخطوة.",
}


@sensitive_variables("token")
def remember(request, response, token, result, kind):
    values = dict(case_ref=result["public_ref"], revision=result["revision"], kind=kind)
    values["binding"] = workspace._binding(
        request, token, f"notice:{values['case_ref']}:{values['revision']}:{kind}"
    )
    response.set_signed_cookie(
        COOKIE,
        json.dumps(values, separators=(",", ":")),
        salt=SALT,
        max_age=90,
        httponly=True,
        samesite="Strict",
        path=workspace.URL,
        secure=False,
    )
    return response


@sensitive_variables("token")
def read(request, token, result):
    raw = request.get_signed_cookie(COOKIE, default="", salt=SALT, max_age=90)
    try:
        if len(raw) > 1024:
            return ""
        value = json.loads(raw)
        if (
            type(value) is not dict
            or set(value) != {"case_ref", "revision", "kind", "binding"}
            or type(value["revision"]) is not int
            or not 1 <= value["revision"] <= result["revision"]
            or value["case_ref"] != result["public_ref"]
            or value["kind"] not in MESSAGES
            or type(value["binding"]) is not str
        ):
            return ""
        expected = workspace._binding(
            request, token, f"notice:{value['case_ref']}:{value['revision']}:{value['kind']}"
        )
        return MESSAGES[value["kind"]] if compare_digest(expected, value["binding"]) else ""
    except (TypeError, ValueError, KeyError):
        return ""


def clear(response):
    response.delete_cookie(COOKIE, path=workspace.URL, samesite="Strict")
    return response
