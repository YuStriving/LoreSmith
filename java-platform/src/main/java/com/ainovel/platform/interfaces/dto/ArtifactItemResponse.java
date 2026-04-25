package com.ainovel.platform.interfaces.dto;

public record ArtifactItemResponse(
        String artifactId,
        String type,
        String name,
        Integer chapter,
        String mimeType,
        String uri,
        String createdAt
) {}
