import { ComponentFixture, TestBed } from "@angular/core/testing";
import { FormsModule } from "@angular/forms";
import { of, throwError } from "rxjs";
import { TaskListComponent } from "./task-list.component";
import { AppService } from "../app.service";
import { Task } from "../task.model";

describe("TaskListComponent", () => {
  let component: TaskListComponent;
  let fixture: ComponentFixture<TaskListComponent>;
  let mockService: jasmine.SpyObj<AppService>;

  const mockTasks: Task[] = [
    {
      id: 1,
      title: "Task 1",
      description: "Desc 1",
      completed: false,
      created_at: "2023-01-01",
    },
    {
      id: 2,
      title: "Task 2",
      description: "Desc 2",
      completed: true,
      created_at: "2023-01-02",
    },
  ];

  beforeEach(async () => {
    const serviceSpy = jasmine.createSpyObj("AppService", [
      "getTasks",
      "addTask",
      "updateTask",
    ]);

    await TestBed.configureTestingModule({
      declarations: [TaskListComponent],
      imports: [FormsModule],
      providers: [{ provide: AppService, useValue: serviceSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(TaskListComponent);
    component = fixture.componentInstance;
    mockService = TestBed.inject(AppService) as jasmine.SpyObj<AppService>;
  });

  it("should create", () => {
    expect(component).toBeTruthy();
  });

  it("should load tasks on init", () => {
    mockService.getTasks.and.returnValue(of(mockTasks));

    component.ngOnInit();

    expect(mockService.getTasks).toHaveBeenCalled();
    expect(component.tasks).toEqual(mockTasks);
    expect(component.loading).toBeFalse();
    expect(component.error).toBe("");
  });

  it("should handle error when loading tasks", () => {
    mockService.getTasks.and.returnValue(
      throwError(() => new Error("API Error")),
    );

    component.ngOnInit();

    expect(component.loading).toBeFalse();
    expect(component.error).toBe("Unable to load tasks from the API.");
  });

  it("should create task", () => {
    mockService.addTask.and.returnValue(of(mockTasks[0]));
    mockService.getTasks.and.returnValue(of(mockTasks));
    component.newTitle = "New Task";
    component.newDescription = "New Desc";

    component.createTask();

    expect(mockService.addTask).toHaveBeenCalledWith({
      title: "New Task",
      description: "New Desc",
    });
    expect(component.newTitle).toBe("");
    expect(component.newDescription).toBe("");
    expect(mockService.getTasks).toHaveBeenCalled();
  });

  it("should not create task with empty title", () => {
    component.newTitle = "   ";
    component.newDescription = "Desc";

    component.createTask();

    expect(mockService.addTask).not.toHaveBeenCalled();
  });

  it("should handle error when creating task", () => {
    mockService.addTask.and.returnValue(
      throwError(() => new Error("API Error")),
    );
    component.newTitle = "New Task";

    component.createTask();

    expect(component.error).toBe("Unable to create task.");
  });

  it("should toggle task completion", () => {
    const task = mockTasks[0];
    const updatedTask = { ...task, completed: true };
    mockService.updateTask.and.returnValue(of(updatedTask));
    mockService.getTasks.and.returnValue(of(mockTasks));

    component.toggleCompletion(task);

    expect(mockService.updateTask).toHaveBeenCalledWith(updatedTask);
    expect(mockService.getTasks).toHaveBeenCalled();
  });

  it("should handle error when updating task", () => {
    const task = mockTasks[0];
    mockService.updateTask.and.returnValue(
      throwError(() => new Error("API Error")),
    );

    component.toggleCompletion(task);

    expect(component.error).toBe("Unable to update task.");
  });
});
