<?php
/** @var array $_ */
/** @var \OCP\IL10N $l */
?>
<div id="app-content" class="fa-app">
<?php if (!$_['allowed']): ?>
	<div class="fa-denied">
		<h2><?php p($l->t('Access denied')); ?></h2>
		<p><?php p($l->t('Only administrators and members of the "attendance" group can view attendance.')); ?></p>
	</div>
<?php else: ?>
	<div id="fa-root"></div>
<?php endif; ?>
</div>
