package com.ainovel.platform.interfaces.dto;

import java.util.List;
import java.util.Map;

public record StoryWorkspaceResponse(
        String storyId,
        String title,
        String premise,
        String style,
        String updatedAt,
        Boolean localOnly,
        List<WorkspaceNodeResponse> nodes,
        String activeNodeId,
        Map<String, String> contentByNodeId,
        List<WorkspaceAssistantMessageResponse> assistantThread,
        WorkspaceRunBridgeResponse runBridge
) {}
