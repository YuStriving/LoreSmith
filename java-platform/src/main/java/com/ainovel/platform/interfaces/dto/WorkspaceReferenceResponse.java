package com.ainovel.platform.interfaces.dto;

import java.util.List;
import java.util.Map;

public record WorkspaceReferenceResponse(
        String premise,
        List<Map<String, Object>> outline,
        List<Map<String, Object>> characters,
        List<Map<String, Object>> worldRules,
        List<Map<String, Object>> timeline,
        List<Map<String, Object>> relationshipState,
        List<Map<String, Object>> foreshadowLedger
) {}
