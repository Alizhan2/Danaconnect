"use client";
import { useLocale, translatePhrase as tr } from "@/lib/i18n";

import { use, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import type { Project, User, DocumentVersion } from "@/lib/types";
import { AppShell } from "@/components/shell";
import { Badge, Button, Field } from "@/components/ui";
import { ProjectForm } from "@/components/workflows/project-form";
import { ReportAction } from "@/components/report-action";
import { ProjectDiscussion, ProjectTeam, PrivateAttachments } from "@/components/collaboration";
import {
  ActionNotice,
  LoadState,
  mutate,
  statusText,
  useAction,
  useLoad,
} from "@/components/workflows/common";
export default function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { locale, tr } = useLocale();
  const { id } = use(params);
  const action = useAction();
  const [motivation, setMotivation] = useState("");
  const [editing, setEditing] = useState(false);
  const [privateDetails, setPrivateDetails] = useState("");
  const [privateLoaded, setPrivateLoaded] = useState(false);
  const [privateDocuments, setPrivateDocuments] = useState<DocumentVersion[]>(
    [],
  );
  const [read, setRead] = useState<string[]>([]);
  useEffect(() => {
    setPrivateDocuments([]);
    setRead([]);
  }, [locale]);
  const load = useLoad(async () => {
    const project = await api<Project>(`/projects/${id}`);
    let user: User | null = null;
    try {
      user = await api<User>("/auth/me");
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    }
    let access = {is_member:false, can_invite:false};
    if(user?.account_status === 'active') {
      try { access = await api<typeof access>(`/projects/${id}/access`); }
      catch(error) {if (!(error instanceof ApiError && [403,404].includes(error.status))) throw error;}
    }
    return { project, user, access };
  }, [id]);
  const project = load.data?.project;
  const user = load.data?.user;
  async function apply(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await mutate("/applications", {
        project_id: id,
        mentor_id: project?.mentor_id || project?.owner_id,
        motivation,
      });
      setMotivation("");
    }, tr("Заявка отправлена. Следите за ответом в кабинете."));
  }
  async function reveal() {
    await action.run(async () => {
      const details = await api<{ private_details: string }>(
        `/projects/${id}/private`,
      );
      setPrivateDetails(details.private_details);
      setPrivateLoaded(true);
    }, tr("Доступ к закрытой части подтверждён"));
  }
  return (
    <AppShell title={project?.title || tr("Проект")}>
      <div className="container page-content">
        <LoadState {...load} retry={load.reload}>
          {project && (
            <div className="stack">
              <div className="profile-grid">
                <section className="panel">
                  <div className="tags">
                    <Badge tone="blue">{tr(statusText(project.stage))}</Badge>
                    <Badge>{tr(statusText(project.visibility_status))}</Badge>
                  </div>
                  <h2 style={{ marginTop: 24 }}>{tr("Проблема")}</h2>
                  <p className="pre-line">{project.problem}</p>
                  <h2>{tr("О проекте")}</h2>
                  <p className="pre-line">{project.description}</p>
                  {user && <ReportAction type="project" entity={id} />}
                  <div className="tags">
                    {project.required_skills.map((skill) => (
                      <Badge key={skill}>{skill}</Badge>
                    ))}
                  </div>
                  <p style={{ marginTop: 20 }}>
                    {tr("Мест в проекте:")} {project.capacity}
                  </p>
                  <Button href="/projects" variant="ghost">
                    {tr("Все проекты")}
                  </Button>
                </section>
                <aside className="panel">
                  <h2>{tr("Участие в проекте")}</h2>
                  <ActionNotice action={action} />
                  {!user ? (
                    <>
                      <p>
                        {tr(
                          "Войдите и пройдите проверку профиля, чтобы отправить заявку.",
                        )}
                      </p>
                      <Button href="/login">{tr("Войти")}</Button>
                    </>
                  ) : user.account_status !== "active" ? (
                    <Button href="/onboarding">
                      {tr("Завершить регистрацию")}
                    </Button>
                  ) : user.id === project.owner_id ? (
                    <>
                      <p>
                        {tr(
                          "Это ваш проект. После изменений публикация потребует повторной проверки.",
                        )}
                      </p>
                      <Button
                        onClick={() => setEditing(!editing)}
                        variant="secondary"
                      >
                        {editing ? tr("Закрыть редактор") : tr("Редактировать")}
                      </Button>
                      <div className="divider" />
                      <h3>{tr("Публикация результата")}</h3>
                      <p>
                        {tr(
                          "Для витрины нужны подтверждённый результат и согласия участников. Согласие можно отозвать.",
                        )}
                      </p>
                      <div className="actions">
                        <Button
                          disabled={action.busy}
                          onClick={() =>
                            action.run(
                              () =>
                                mutate(`/projects/${id}/showcase-consent`, {
                                  accepted: true,
                                }),
                              tr("Согласие на витрину сохранено"),
                            )
                          }
                        >
                          {tr("Разрешить витрину")}
                        </Button>
                        <Button
                          variant="secondary"
                          disabled={action.busy}
                          onClick={() =>
                            action.run(
                              () =>
                                mutate(`/projects/${id}/showcase-consent`, {
                                  accepted: false,
                                }),
                              tr("Согласие на витрину отозвано"),
                            )
                          }
                        >
                          {tr("Отозвать")}
                        </Button>
                      </div>
                    </>
                  ) : user.role === "mentee" && project.mentor_id ? (
                    <form className="form-stack" onSubmit={apply}>
                      <Field label={tr("Почему вы хотите участвовать")}>
                        <textarea
                          required
                          minLength={20}
                          maxLength={5000}
                          value={motivation}
                          onChange={(e) => setMotivation(e.target.value)}
                        />
                      </Field>
                      <Button disabled={action.busy} type="submit">
                        {tr("Отправить заявку")}
                      </Button>
                    </form>
                  ) : (
                    <>
                      <p>
                        {tr(
                          "Для этого проекта индивидуальный запрос можно обсудить с ментором через каталог и кабинет.",
                        )}
                      </p>
                      <Button href="/catalog">{tr("Найти ментора")}</Button>
                    </>
                  )}
                </aside>
              </div>
              {user && load.data?.access.is_member &&
                (user.id !== project.owner_id ||
                  user.account_status !== "active") && (
                  <section className="panel">
                    <h2>{tr("Согласие на витрину")}</h2>
                    <p>
                      {tr(
                        "Согласие доступно участникам этого проекта. Для публикации нужны подтверждённый результат и согласия всех участников; его можно отозвать в любой момент.",
                      )}
                    </p>
                    <ActionNotice action={action} />
                    <div className="actions">
                      <Button
                        disabled={action.busy}
                        onClick={() =>
                          action.run(
                            () =>
                              mutate(`/projects/${id}/showcase-consent`, {
                                accepted: true,
                              }),
                            tr("Согласие на витрину сохранено"),
                          )
                        }
                      >
                        {tr("Разрешить публикацию")}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={action.busy}
                        onClick={() =>
                          action.run(
                            () =>
                              mutate(`/projects/${id}/showcase-consent`, {
                                accepted: false,
                              }),
                            tr("Согласие отозвано"),
                          )
                        }
                      >
                        {tr("Отозвать согласие")}
                      </Button>
                    </div>
                  </section>
                )}
              {editing && (
                <section className="panel">
                  <ProjectForm
                    project={project}
                    onSaved={() => {
                      setEditing(false);
                      load.reload();
                    }}
                  />
                </section>
              )}
              {user && load.data?.access.is_member && (
                <section className="panel">
                  <h2>{tr("Закрытая часть проекта")}</h2>
                  <p>
                    {tr(
                      "Доступ предоставляется участникам после проверки актуальных документов.",
                    )}
                  </p>
                  <div className="actions">
                    <Button disabled={action.busy} onClick={reveal}>
                      {tr("Запросить доступ")}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() =>
                        action.run(async () => {
                          setPrivateDocuments(
                            (await api<DocumentVersion[]>("/documents")).filter(
                              (d) => d.scope === "private_project",
                            ),
                          );
                        }, tr("Документы загружены"))
                      }
                    >
                      {tr("Открыть документы доступа")}
                    </Button>
                  </div>
                  {privateDocuments.map((document) => (
                    <div key={document.id} style={{ marginTop: 20 }}>
                      <details>
                        <summary>
                          {document.title} · {document.version}
                        </summary>
                        <div
                          className="document-content"
                          lang={document.content_locale || "ru"}
                        >
                          {document.content}
                        </div>
                        {locale !== "ru" &&
                          document.content_locale !== locale && (
                            <p className="field-hint">
                              {tr(
                                "Перевод документа пока недоступен. Показана исходная русская версия.",
                              )}
                            </p>
                          )}
                      </details>
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={
                            document.accepted || read.includes(document.id)
                          }
                          disabled={document.accepted}
                          onChange={(e) =>
                            setRead(
                              e.target.checked
                                ? [...read, document.id]
                                : read.filter((value) => value !== document.id),
                            )
                          }
                        />
                        {tr("Я ознакомился(ась) с проектом документа")}
                      </label>
                      {!document.accepted && (
                        <Button
                          disabled={!read.includes(document.id) || action.busy}
                          onClick={() =>
                            action.run(async () => {
                              await mutate(
                                `/documents/${document.id}/consent`,
                                {
                                  content_hash: document.content_hash,
                                  content_locale: document.content_locale,
                                },
                              );
                              setPrivateDocuments((current) =>
                                current.map((d) =>
                                  d.id === document.id
                                    ? { ...d, accepted: true }
                                    : d,
                                ),
                              );
                            }, tr("Ознакомление сохранено"))
                          }
                        >
                          {tr("Подтвердить ознакомление")}
                        </Button>
                      )}
                    </div>
                  ))}
                  {privateLoaded && (
                    <div className="document-content" style={{ marginTop: 20 }}>
                      {privateDetails || tr("Закрытых деталей нет.")}
                    </div>
                  )}
                </section>
              )}
              {user?.account_status === 'active' && <ProjectDiscussion projectId={id} user={user}/>}
              {user && load.data?.access.is_member && <>
                <ProjectTeam key={`team-${privateLoaded}`} projectId={id} user={user} canInvite={load.data.access.can_invite} onChanged={async () => {setPrivateDetails("");setPrivateLoaded(false);setPrivateDocuments([]);setRead([]);await load.reload();}}/>
                <PrivateAttachments key={`files-${privateLoaded}`} projectId={id} user={user} ownerId={project.owner_id}/>
                <ProjectDiscussion key={`discussion-${privateLoaded}`} projectId={id} user={user} scope="team"/>
              </>}
            </div>
          )}
        </LoadState>
      </div>
    </AppShell>
  );
}
