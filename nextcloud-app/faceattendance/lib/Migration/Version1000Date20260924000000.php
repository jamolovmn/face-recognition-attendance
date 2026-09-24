<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Migration;

use Closure;
use OCP\DB\ISchemaWrapper;
use OCP\DB\Types;
use OCP\Migration\IOutput;
use OCP\Migration\SimpleMigrationStep;

class Version1000Date20260924000000 extends SimpleMigrationStep {
	public function changeSchema(IOutput $output, Closure $schemaClosure, array $options): ?ISchemaWrapper {
		/** @var ISchemaWrapper $schema */
		$schema = $schemaClosure();
		if ($schema->hasTable('fa_events')) {
			return null;
		}
		$table = $schema->createTable('fa_events');
		$table->addColumn('id', Types::BIGINT, ['autoincrement' => true, 'notnull' => true, 'unsigned' => true]);
		$table->addColumn('uid', Types::STRING, ['notnull' => true, 'length' => 64]);
		$table->addColumn('person', Types::STRING, ['notnull' => false, 'length' => 128]);
		$table->addColumn('camera', Types::STRING, ['notnull' => true, 'length' => 64]);
		$table->addColumn('room', Types::STRING, ['notnull' => true, 'length' => 128]);
		$table->addColumn('score', Types::FLOAT, ['notnull' => true, 'default' => 0]);
		$table->addColumn('ts', Types::BIGINT, ['notnull' => true, 'unsigned' => true]);
		$table->addColumn('snapshot', Types::STRING, ['notnull' => false, 'length' => 128]);
		$table->setPrimaryKey(['id']);
		$table->addUniqueIndex(['uid'], 'fa_events_uid');
		$table->addIndex(['ts'], 'fa_events_ts');
		$table->addIndex(['person', 'ts'], 'fa_events_person_ts');
		return $schema;
	}
}
