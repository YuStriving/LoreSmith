package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.StoryWorkspaceIssueRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceNodeRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceReferenceRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceVersionRecord;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface StoryWorkspaceRepository {
    Optional<StoryWorkspaceRecord> findWorkspace(String storyId);
    StoryWorkspaceRecord saveWorkspace(StoryWorkspaceRecord workspace);
    StoryWorkspaceNodeRecord saveNode(StoryWorkspaceNodeRecord node);
    void saveContent(String storyId, String nodeId, String content, Instant updatedAt);
    StoryWorkspaceVersionRecord saveVersion(StoryWorkspaceVersionRecord version);
    void setActiveNode(String storyId, String activeNodeId, Instant updatedAt);
    Optional<StoryWorkspaceNodeRecord> findNode(String storyId, String nodeId);
    Optional<String> findContent(String storyId, String nodeId);
    Optional<StoryWorkspaceVersionRecord> findVersion(String storyId, String nodeId, String versionId);
    Optional<StoryWorkspaceReferenceRecord> findReference(String storyId);
    void upsertReference(StoryWorkspaceReferenceRecord record);
    void replaceIssues(String storyId, List<StoryWorkspaceIssueRecord> issues, Instant updatedAt);
    void updateNodeParent(String storyId, String nodeId, String parentId, Instant updatedAt);
    void deleteNode(String storyId, String nodeId);
    void deleteIssuesByNodeIds(String storyId, List<String> nodeIds);
    void updateRunBridge(String storyId, String activeRunId, Integer runAfterSeq, String runSyncStatus, Instant runSyncUpdatedAt, Instant updatedAt);
}
