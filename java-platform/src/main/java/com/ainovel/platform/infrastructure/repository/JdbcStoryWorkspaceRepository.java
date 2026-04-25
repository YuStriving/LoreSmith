package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.StoryWorkspaceBeatRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceIssueRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceMessageRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceNodeRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceReferenceRecord;
import com.ainovel.platform.domain.model.StoryWorkspaceVersionRecord;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

@Repository
public class JdbcStoryWorkspaceRepository implements StoryWorkspaceRepository {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<List<Map<String, Object>>> LIST_OF_MAPS = new TypeReference<>() {};

    private final JdbcTemplate jdbcTemplate;

    public JdbcStoryWorkspaceRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public Optional<StoryWorkspaceRecord> findWorkspace(String storyId) {
        List<StoryWorkspaceRecord> workspaces = jdbcTemplate.query("""
                SELECT p.story_id, p.title, p.premise, p.style_code, w.updated_at, w.active_node_id,
                       w.active_run_id, w.run_after_seq, w.run_sync_status, w.run_sync_updated_at
                FROM story_project p
                JOIN story_workspace w ON w.story_id = p.story_id
                WHERE p.story_id = ?
                """, (rs, rowNum) -> new StoryWorkspaceRecord(
                rs.getString("story_id"),
                rs.getString("title"),
                rs.getString("premise"),
                rs.getString("style_code"),
                rs.getTimestamp("updated_at").toInstant(),
                rs.getString("active_node_id"),
                rs.getString("active_run_id"),
                rs.getInt("run_after_seq"),
                rs.getString("run_sync_status"),
                rs.getTimestamp("run_sync_updated_at") == null ? null : rs.getTimestamp("run_sync_updated_at").toInstant(),
                List.of(),
                Map.of(),
                List.of(),
                Map.of(),
                List.of(),
                Map.of()
        ), storyId);
        if (workspaces.isEmpty()) {
            return Optional.empty();
        }

        StoryWorkspaceRecord workspace = workspaces.getFirst();
        List<StoryWorkspaceNodeRecord> nodes = jdbcTemplate.query("""
                SELECT node_id, story_id, parent_id, type, title, display_order, summary, created_at, updated_at
                FROM story_workspace_node
                WHERE story_id = ?
                ORDER BY created_at ASC
                """, this::mapNode, storyId);

        Map<String, String> contentByNodeId = new LinkedHashMap<>();
        List<Map.Entry<String, String>> contentRows = jdbcTemplate.query("""
                SELECT node_id, content
                FROM story_workspace_content
                WHERE story_id = ?
                ORDER BY updated_at ASC
                """, (rs, rowNum) -> Map.entry(rs.getString("node_id"), rs.getString("content")), storyId);
        contentRows.forEach(entry -> contentByNodeId.put(entry.getKey(), entry.getValue()));

        List<StoryWorkspaceMessageRecord> assistantThread = jdbcTemplate.query("""
                SELECT message_id, story_id, role, content, created_at
                FROM story_workspace_message
                WHERE story_id = ?
                ORDER BY created_at ASC
                """, this::mapMessage, storyId);

        Map<String, List<StoryWorkspaceBeatRecord>> beatByNodeId = jdbcTemplate.query("""
                SELECT beat_id, story_id, node_id, title, goal, conflict, outcome, display_order, status, created_at, updated_at
                FROM story_workspace_beat
                WHERE story_id = ?
                ORDER BY node_id ASC, display_order ASC, created_at ASC
                """, rs -> {
            Map<String, List<StoryWorkspaceBeatRecord>> grouped = new LinkedHashMap<>();
            while (rs.next()) {
                StoryWorkspaceBeatRecord beat = mapBeat(rs, 0);
                grouped.computeIfAbsent(beat.nodeId(), ignored -> new java.util.ArrayList<>()).add(beat);
            }
            return grouped;
        }, storyId);

        List<StoryWorkspaceIssueRecord> issues = jdbcTemplate.query("""
                SELECT issue_id, story_id, node_id, severity, category, title, description, status, created_at, updated_at
                FROM story_workspace_issue
                WHERE story_id = ?
                ORDER BY created_at ASC
                """, this::mapIssue, storyId);

        Map<String, List<StoryWorkspaceVersionRecord>> versionsByNodeId = jdbcTemplate.query("""
                SELECT version_id, story_id, node_id, label, content, source, created_at
                FROM story_workspace_version
                WHERE story_id = ?
                ORDER BY node_id ASC, created_at ASC
                """, rs -> {
            Map<String, List<StoryWorkspaceVersionRecord>> grouped = new LinkedHashMap<>();
            while (rs.next()) {
                StoryWorkspaceVersionRecord version = mapVersion(rs, 0);
                grouped.computeIfAbsent(version.nodeId(), ignored -> new java.util.ArrayList<>()).add(version);
            }
            return grouped;
        }, storyId);

        return Optional.of(new StoryWorkspaceRecord(
                workspace.storyId(),
                workspace.title(),
                workspace.premise(),
                workspace.style(),
                workspace.updatedAt(),
                workspace.activeNodeId(),
                workspace.activeRunId(),
                workspace.runAfterSeq(),
                workspace.runSyncStatus(),
                workspace.runSyncUpdatedAt(),
                nodes,
                contentByNodeId,
                assistantThread,
                beatByNodeId,
                issues,
                versionsByNodeId
        ));
    }

    @Override
    public StoryWorkspaceRecord saveWorkspace(StoryWorkspaceRecord workspace) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace (story_id, active_node_id, active_run_id, run_after_seq, run_sync_status, run_sync_updated_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (story_id) DO UPDATE SET
                    active_node_id = EXCLUDED.active_node_id,
                    active_run_id = EXCLUDED.active_run_id,
                    run_after_seq = EXCLUDED.run_after_seq,
                    run_sync_status = EXCLUDED.run_sync_status,
                    run_sync_updated_at = EXCLUDED.run_sync_updated_at,
                    updated_at = EXCLUDED.updated_at
                """,
                workspace.storyId(),
                workspace.activeNodeId(),
                workspace.activeRunId(),
                workspace.runAfterSeq() == null ? 0 : workspace.runAfterSeq(),
                workspace.runSyncStatus() == null ? "idle" : workspace.runSyncStatus(),
                workspace.runSyncUpdatedAt() == null ? null : Timestamp.from(workspace.runSyncUpdatedAt()),
                Timestamp.from(workspace.updatedAt())
        );

        workspace.nodes().forEach(this::saveNode);
        workspace.contentByNodeId().forEach((nodeId, content) -> saveContent(workspace.storyId(), nodeId, content, workspace.updatedAt()));
        workspace.assistantThread().forEach(this::saveMessage);
        workspace.beatByNodeId().values().forEach(beats -> beats.forEach(this::saveBeat));
        workspace.consistencyIssues().forEach(this::saveIssue);
        workspace.versionsByNodeId().values().forEach(versions -> versions.forEach(this::saveVersion));
        return workspace;
    }

    @Override
    public StoryWorkspaceNodeRecord saveNode(StoryWorkspaceNodeRecord node) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_node (node_id, story_id, parent_id, type, title, display_order, summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (node_id) DO UPDATE SET
                    parent_id = EXCLUDED.parent_id,
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    display_order = EXCLUDED.display_order,
                    summary = EXCLUDED.summary,
                    updated_at = EXCLUDED.updated_at
                """,
                node.nodeId(),
                node.storyId(),
                node.parentId(),
                node.type(),
                node.title(),
                node.displayOrder(),
                node.summary(),
                Timestamp.from(node.createdAt()),
                Timestamp.from(node.updatedAt())
        );
        return node;
    }

    @Override
    public void saveContent(String storyId, String nodeId, String content, Instant updatedAt) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_content (node_id, story_id, content, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (node_id) DO UPDATE SET
                    story_id = EXCLUDED.story_id,
                    content = EXCLUDED.content,
                    updated_at = EXCLUDED.updated_at
                """,
                nodeId,
                storyId,
                content,
                Timestamp.from(updatedAt)
        );
    }

    @Override
    public StoryWorkspaceVersionRecord saveVersion(StoryWorkspaceVersionRecord version) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_version (version_id, story_id, node_id, label, content, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (version_id) DO UPDATE SET
                    label = EXCLUDED.label,
                    content = EXCLUDED.content,
                    source = EXCLUDED.source,
                    created_at = EXCLUDED.created_at
                """,
                version.versionId(),
                version.storyId(),
                version.nodeId(),
                version.label(),
                version.content(),
                version.source(),
                Timestamp.from(version.createdAt())
        );
        jdbcTemplate.update("UPDATE story_workspace SET updated_at = ? WHERE story_id = ?", Timestamp.from(version.createdAt()), version.storyId());
        return version;
    }

    @Override
    public void setActiveNode(String storyId, String activeNodeId, Instant updatedAt) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace (story_id, active_node_id, run_after_seq, run_sync_status, updated_at)
                VALUES (?, ?, 0, 'idle', ?)
                ON CONFLICT (story_id) DO UPDATE SET
                    active_node_id = EXCLUDED.active_node_id,
                    updated_at = EXCLUDED.updated_at
                """,
                storyId,
                activeNodeId,
                Timestamp.from(updatedAt)
        );
    }

    @Override
    public Optional<StoryWorkspaceNodeRecord> findNode(String storyId, String nodeId) {
        List<StoryWorkspaceNodeRecord> rows = jdbcTemplate.query("""
                SELECT node_id, story_id, parent_id, type, title, display_order, summary, created_at, updated_at
                FROM story_workspace_node
                WHERE story_id = ? AND node_id = ?
                """, this::mapNode, storyId, nodeId);
        return rows.stream().findFirst();
    }

    @Override
    public Optional<String> findContent(String storyId, String nodeId) {
        List<String> rows = jdbcTemplate.query("""
                SELECT content
                FROM story_workspace_content
                WHERE story_id = ? AND node_id = ?
                """, (rs, rowNum) -> rs.getString("content"), storyId, nodeId);
        return rows.stream().findFirst();
    }

    @Override
    public Optional<StoryWorkspaceVersionRecord> findVersion(String storyId, String nodeId, String versionId) {
        List<StoryWorkspaceVersionRecord> rows = jdbcTemplate.query("""
                SELECT version_id, story_id, node_id, label, content, source, created_at
                FROM story_workspace_version
                WHERE story_id = ? AND node_id = ? AND version_id = ?
                """, this::mapVersion, storyId, nodeId, versionId);
        return rows.stream().findFirst();
    }

    @Override
    public Optional<StoryWorkspaceReferenceRecord> findReference(String storyId) {
        List<StoryWorkspaceReferenceRecord> rows = jdbcTemplate.query("""
                SELECT story_id, premise_md, outline_json::text AS outline_json, characters_json::text AS characters_json,
                       world_rules_json::text AS world_rules_json, timeline_json::text AS timeline_json,
                       relationship_state_json::text AS relationship_state_json,
                       foreshadow_ledger_json::text AS foreshadow_ledger_json, source, updated_at
                FROM story_workspace_reference
                WHERE story_id = ?
                """, this::mapReference, storyId);
        return rows.stream().findFirst();
    }

    @Override
    public void upsertReference(StoryWorkspaceReferenceRecord record) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_reference (
                    story_id, premise_md, outline_json, characters_json, world_rules_json,
                    timeline_json, relationship_state_json, foreshadow_ledger_json, source, updated_at
                )
                VALUES (?, ?, ?::jsonb, ?::jsonb, ?::jsonb, ?::jsonb, ?::jsonb, ?::jsonb, ?, ?)
                ON CONFLICT (story_id) DO UPDATE SET
                    premise_md = EXCLUDED.premise_md,
                    outline_json = EXCLUDED.outline_json,
                    characters_json = EXCLUDED.characters_json,
                    world_rules_json = EXCLUDED.world_rules_json,
                    timeline_json = EXCLUDED.timeline_json,
                    relationship_state_json = EXCLUDED.relationship_state_json,
                    foreshadow_ledger_json = EXCLUDED.foreshadow_ledger_json,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
                """,
                record.storyId(),
                record.premiseMd(),
                toJson(record.outline()),
                toJson(record.characters()),
                toJson(record.worldRules()),
                toJson(record.timeline()),
                toJson(record.relationshipState()),
                toJson(record.foreshadowLedger()),
                record.source(),
                Timestamp.from(record.updatedAt())
        );
    }

    @Override
    public void replaceIssues(String storyId, List<StoryWorkspaceIssueRecord> issues, Instant updatedAt) {
        jdbcTemplate.update("DELETE FROM story_workspace_issue WHERE story_id = ?", storyId);
        issues.forEach(this::saveIssue);
        jdbcTemplate.update("UPDATE story_workspace SET updated_at = ? WHERE story_id = ?", Timestamp.from(updatedAt), storyId);
    }

    @Override
    public void updateNodeParent(String storyId, String nodeId, String parentId, Instant updatedAt) {
        jdbcTemplate.update("""
                UPDATE story_workspace_node
                SET parent_id = ?, updated_at = ?
                WHERE story_id = ? AND node_id = ?
                """,
                parentId,
                Timestamp.from(updatedAt),
                storyId,
                nodeId
        );
    }

    @Override
    public void deleteNode(String storyId, String nodeId) {
        jdbcTemplate.update("DELETE FROM story_workspace_node WHERE story_id = ? AND node_id = ?", storyId, nodeId);
    }

    @Override
    public void deleteIssuesByNodeIds(String storyId, List<String> nodeIds) {
        if (nodeIds == null || nodeIds.isEmpty()) {
            return;
        }
        String placeholders = nodeIds.stream().map(ignored -> "?").collect(Collectors.joining(", "));
        List<Object> params = new java.util.ArrayList<>();
        params.add(storyId);
        params.addAll(nodeIds);
        jdbcTemplate.update("DELETE FROM story_workspace_issue WHERE story_id = ? AND node_id IN (" + placeholders + ")", params.toArray());
    }

    @Override
    public void updateRunBridge(String storyId, String activeRunId, Integer runAfterSeq, String runSyncStatus, Instant runSyncUpdatedAt, Instant updatedAt) {
        jdbcTemplate.update("""
                UPDATE story_workspace
                SET active_run_id = ?,
                    run_after_seq = ?,
                    run_sync_status = ?,
                    run_sync_updated_at = ?,
                    updated_at = ?
                WHERE story_id = ?
                """,
                activeRunId,
                runAfterSeq == null ? 0 : runAfterSeq,
                runSyncStatus,
                runSyncUpdatedAt == null ? null : Timestamp.from(runSyncUpdatedAt),
                Timestamp.from(updatedAt),
                storyId
        );
    }

    private void saveMessage(StoryWorkspaceMessageRecord message) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_message (message_id, story_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (message_id) DO UPDATE SET
                    role = EXCLUDED.role,
                    content = EXCLUDED.content,
                    created_at = EXCLUDED.created_at
                """,
                message.messageId(),
                message.storyId(),
                message.role(),
                message.content(),
                Timestamp.from(message.createdAt())
        );
    }

    private void saveBeat(StoryWorkspaceBeatRecord beat) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_beat (beat_id, story_id, node_id, title, goal, conflict, outcome, display_order, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (beat_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    goal = EXCLUDED.goal,
                    conflict = EXCLUDED.conflict,
                    outcome = EXCLUDED.outcome,
                    display_order = EXCLUDED.display_order,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                beat.beatId(),
                beat.storyId(),
                beat.nodeId(),
                beat.title(),
                beat.goal(),
                beat.conflict(),
                beat.outcome(),
                beat.displayOrder(),
                beat.status(),
                Timestamp.from(beat.createdAt()),
                Timestamp.from(beat.updatedAt())
        );
    }

    private void saveIssue(StoryWorkspaceIssueRecord issue) {
        jdbcTemplate.update("""
                INSERT INTO story_workspace_issue (issue_id, story_id, node_id, severity, category, title, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (issue_id) DO UPDATE SET
                    node_id = EXCLUDED.node_id,
                    severity = EXCLUDED.severity,
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                issue.issueId(),
                issue.storyId(),
                issue.nodeId(),
                issue.severity(),
                issue.category(),
                issue.title(),
                issue.description(),
                issue.status(),
                Timestamp.from(issue.createdAt()),
                Timestamp.from(issue.updatedAt())
        );
    }

    private StoryWorkspaceNodeRecord mapNode(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceNodeRecord(
                rs.getString("node_id"),
                rs.getString("story_id"),
                rs.getString("parent_id"),
                rs.getString("type"),
                rs.getString("title"),
                rs.getInt("display_order"),
                rs.getString("summary"),
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant()
        );
    }

    private StoryWorkspaceVersionRecord mapVersion(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceVersionRecord(
                rs.getString("version_id"),
                rs.getString("story_id"),
                rs.getString("node_id"),
                rs.getString("label"),
                rs.getString("content"),
                rs.getString("source"),
                rs.getTimestamp("created_at").toInstant()
        );
    }

    private StoryWorkspaceMessageRecord mapMessage(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceMessageRecord(
                rs.getString("message_id"),
                rs.getString("story_id"),
                rs.getString("role"),
                rs.getString("content"),
                rs.getTimestamp("created_at").toInstant()
        );
    }

    private StoryWorkspaceIssueRecord mapIssue(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceIssueRecord(
                rs.getString("issue_id"),
                rs.getString("story_id"),
                rs.getString("node_id"),
                rs.getString("severity"),
                rs.getString("category"),
                rs.getString("title"),
                rs.getString("description"),
                rs.getString("status"),
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant()
        );
    }

    private StoryWorkspaceBeatRecord mapBeat(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceBeatRecord(
                rs.getString("beat_id"),
                rs.getString("story_id"),
                rs.getString("node_id"),
                rs.getString("title"),
                rs.getString("goal"),
                rs.getString("conflict"),
                rs.getString("outcome"),
                rs.getInt("display_order"),
                rs.getString("status"),
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant()
        );
    }

    private StoryWorkspaceReferenceRecord mapReference(ResultSet rs, int rowNum) throws SQLException {
        return new StoryWorkspaceReferenceRecord(
                rs.getString("story_id"),
                rs.getString("premise_md"),
                fromJsonArray(rs.getString("outline_json")),
                fromJsonArray(rs.getString("characters_json")),
                fromJsonArray(rs.getString("world_rules_json")),
                fromJsonArray(rs.getString("timeline_json")),
                fromJsonArray(rs.getString("relationship_state_json")),
                fromJsonArray(rs.getString("foreshadow_ledger_json")),
                rs.getString("source"),
                rs.getTimestamp("updated_at").toInstant()
        );
    }

    private String toJson(List<Map<String, Object>> value) {
        try {
            return OBJECT_MAPPER.writeValueAsString(value == null ? List.of() : value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("failed to serialize workspace reference json", ex);
        }
    }

    private List<Map<String, Object>> fromJsonArray(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        try {
            return OBJECT_MAPPER.readValue(value, LIST_OF_MAPS);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("failed to parse workspace reference json", ex);
        }
    }
}
