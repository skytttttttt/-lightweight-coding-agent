def add_task(tasks, title, done=False):
    tasks.append({'title': title, 'done': done})
    return tasks

def pending(tasks):
    return [t for t in tasks if not t['done']]
