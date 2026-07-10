import type {
  CaseDocument,
  ReviewPoint,
  ReviewTarget,
  SuiteBootstrap,
} from '../api/types.ts'

export function point(
  id: string,
  timestamp_s: number,
  expect_json = 'false',
): ReviewPoint {
  return {
    id,
    timestamp_s,
    expect_type: expect_json === 'true' || expect_json === 'false' ? 'boolean' : 'number',
    expect_json,
    field: null,
    compare: { mode: null, tolerance: null },
    comment: null,
    origin: { block_index: 0, kind: 'at', every_s: null },
  }
}

export function target(
  id: string,
  points: ReviewPoint[] = [point(`${id}-point`, 1)],
): ReviewTarget {
  return {
    id,
    label: id.replaceAll('_', ' '),
    details_yaml: `label: ${id}\n`,
    points,
    display_groups: points.map((item, index) => ({
      id: `group-${index}`,
      kind: 'at',
      point_ids: [item.id],
      start_s: null,
      end_s: null,
      every_s: null,
      timestamps_s: [item.timestamp_s],
    })),
  }
}

export function document(
  targets: ReviewTarget[] = [target('target_a'), target('target_b')],
): CaseDocument {
  return {
    id: 'case-001.yaml',
    name: 'case-001',
    revision: 'revision-1',
    status: 'ready',
    editing_enabled: true,
    load_error: null,
    description: 'A fixture case',
    source_yaml: 'video: fixture.mp4\n',
    video: {
      url: '/api/cases/case-001.yaml/video',
      display_path: 'fixture.mp4',
      content_type: 'video/mp4',
      duration_s: 10,
      width: 64,
      height: 64,
      frame_count: 10,
    },
    targets,
    validation_issues: [],
  }
}

export function suite(): SuiteBootstrap {
  return {
    eval_dir: '/tmp/eval',
    write_token: 'secret',
    config_source_yaml: 'sampling:\n  every_s: 0.5\n',
    cases: [
      {
        id: 'case-001.yaml',
        name: 'case-001',
        file_name: 'case-001.yaml',
        description: 'A fixture case',
        target_count: 2,
        point_count: 2,
        status: 'ready',
        error: null,
      },
      {
        id: 'case-002.yml',
        name: 'case-002',
        file_name: 'case-002.yml',
        description: 'Another fixture case',
        target_count: 1,
        point_count: 1,
        status: 'ready',
        error: null,
      },
    ],
  }
}
