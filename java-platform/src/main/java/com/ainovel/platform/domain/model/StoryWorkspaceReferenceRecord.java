package com.ainovel.platform.domain.model;

import java.time.Instant;
import java.util.List;
import java.util.Map;

public record StoryWorkspaceReferenceRecord(
        String storyId,
        String premiseMd,
        List<Map<String, Object>> outline,
        List<Map<String, Object>> characters,
        List<Map<String, Object>> worldRules,
        List<Map<String, Object>> timeline,
        List<Map<String, Object>> relationshipState,
        List<Map<String, Object>> foreshadowLedger,
        String source,
        Instant updatedAt
) {}
