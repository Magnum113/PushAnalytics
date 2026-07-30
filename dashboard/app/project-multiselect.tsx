type ProjectOption = {
  id: string;
  name: string;
  shortName: string;
  count?: number;
};

type ProjectMultiSelectProps = {
  projects: ProjectOption[];
  selectedIds: string[];
  onChange: (projectIds: string[]) => void;
};

export function ProjectMultiSelect({
  projects,
  selectedIds,
  onChange,
}: ProjectMultiSelectProps) {
  const selected = new Set(selectedIds);
  const allSelected =
    projects.length > 0 && selected.size === projects.length;

  function toggleProject(projectId: string) {
    if (selected.has(projectId)) {
      if (selected.size === 1) return;
      onChange(selectedIds.filter((id) => id !== projectId));
      return;
    }
    onChange([...selectedIds, projectId]);
  }

  return (
    <div className="command-control project-multi-filter">
      <span>Проекты пушей</span>
      <div
        className="project-chip-list"
        role="group"
        aria-label="Выбранные проекты пушей"
      >
        <button
          type="button"
          className={allSelected ? "selected" : ""}
          aria-pressed={allSelected}
          onClick={() => onChange(projects.map((project) => project.id))}
        >
          Все
        </button>
        {projects.map((project) => {
          const isSelected = selected.has(project.id);
          return (
            <button
              type="button"
              key={project.id}
              className={isSelected ? "selected" : ""}
              aria-pressed={isSelected}
              onClick={() => toggleProject(project.id)}
              title={project.name}
            >
              {project.shortName}
              {project.count === undefined ? "" : ` · ${project.count}`}
            </button>
          );
        })}
      </div>
      <small className="project-scope-note">
        Покупки учитываются только внутри проекта каждого пуша
      </small>
    </div>
  );
}
